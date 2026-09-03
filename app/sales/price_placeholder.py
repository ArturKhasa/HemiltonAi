"""Плейсхолдер цены в текстах скриптов: «[цена:свитшот]» → «5 990 ₽».

Скрипты, отправляемые связкой (follow_up_script_id), уходят клиенту дословно —
модель их не переписывает, и это ровно то, что нужно для расчёта сразу после
похвалы. Но цену внутрь такого скрипта нельзя вписывать руками: восемь ценовых
скриптов из выгрузки ОП именно так и протухли — они до сих пор обещают 5 990 ₽
и 6 680 ₽, тогда как в товарной матрице свитшот стоит 4 990 ₽ по акции.

Поэтому цена в тексте скрипта — ссылка на товарную матрицу, а не число.
Матрица остаётся единственным источником правды, редактировать её достаточно в
одном месте.
"""
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.sales.prices import order_total
from app.sales.products import ProductService

logger = logging.getLogger(__name__)

# «[цена:свитшот]» — колонка «Цена» матрицы: её называем клиенту ПЕРВОЙ.
#
# «[минимальная-цена:свитшот]» — СЛЕДУЮЩАЯ УСТУПКА, а не сразу дно. ОП (10
# августа, 16:28): «Изначально предлагаем за 5990 (вместо 7990). Если есть
# возражение дорого: 1. Сначала попытка отработать без скидки, объяснить ценность
# за 5990. 2. Если реакции нет или она негативная — предлагаем по скидке за 5490.
# 3. Если реакция снова негативная, можно предложить за 4990». Плейсхолдер
# спускает ровно на одну ступень от той цены, которую клиент уже слышал, поэтому
# один и тот же скрипт отработки годится и для второго шага, и для третьего.
#
# «[цена-со-скидкой:свитшот]» — явно средняя ступень, если скрипт написан именно
# под неё. «[цена-до-скидки:...]» остаётся синонимом «[цена:...]»: так писались
# первые скрипты, и менять их все разом ради одного слова незачем.
#
# «[сумма-заказа:свитшот]» — итог заказа: сколько клиенту НАЗВАЛИ в этом диалоге,
# а не сколько стоит товар из скобок. Товар в скобках остаётся запасным вариантом
# на случай, когда цену ещё не называли. Появился 03.09 по замечанию РОПа:
# «клиент пришёл за комплектом, ИИ отправляет ему цену на один свитшот». Скрипт
# оформления называл сумму через «[цена:свитшот]», то есть всегда цену одного
# изделия из матрицы, — и клиент с рекламной метки на комплект (5 490 + 3 490 =
# 8 980 ₽) видел в сумме заказа 5 990 ₽. За две недели так ушло 133 сообщения.
_PRICE_PLACEHOLDER_RE = re.compile(
    r"\[(минимальная-цена|цена-со-скидкой|цена-до-скидки|сумма-заказа|цена):([^\]]+)\]",
    re.IGNORECASE,
)

# «[ссылка-оплаты]» — счёт клиенту. Пока платёжной интеграции нет, подставляется
# заглушка из настроек (см. config.PAYMENT_LINK_URL): менеджер выставлял счёт
# руками, и без подстановки скрипт обещал ссылку, не присылая ничего.
_PAYMENT_LINK_PLACEHOLDER_RE = re.compile(r"\[ссылка-оплаты\]", re.IGNORECASE)


def format_price(value) -> str:
    """4990 → «4 990 ₽». Неразрывный пробел, чтобы сумма не рвалась переносом."""
    return f"{int(value):,}".replace(",", " ") + " ₽"


def payment_link_configured() -> bool:
    """Настроен ли реальный счёт. Нет — до оплаты диалог доводит куратор."""
    from app.config import settings

    return bool((settings.PAYMENT_LINK_URL or "").strip())


def _render_payment_link(text: str) -> str:
    if not _PAYMENT_LINK_PLACEHOLDER_RE.search(text):
        return text
    from app.config import settings
    url = (settings.PAYMENT_LINK_URL or "").strip()
    if not url:
        # Ссылки нет — вырезаем предложение с плейсхолдером целиком. «Вот
        # счёт-ссылка на 500 рублей:» без самой ссылки хуже, чем её отсутствие.
        logger.info("ссылка на оплату не настроена — фраза со ссылкой вырезана")
        return _strip_payment_sentence(text)
    return _PAYMENT_LINK_PLACEHOLDER_RE.sub(url, text)


def _strip_payment_sentence(text: str) -> str:
    kept = []
    for line in text.split("\n"):
        if not _PAYMENT_LINK_PLACEHOLDER_RE.search(line):
            kept.append(line)
            continue
        masked = _PAYMENT_LINK_PLACEHOLDER_RE.sub("\x00", line)
        line = "".join(
            part for part in re.findall(r"[^.!?]*(?:[.!?]+\s*|$)", masked) if "\x00" not in part
        ).strip()
        if line:
            kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def price_ladder(product) -> list[int]:
    """Ступени уступки сверху вниз: «Цена» → «Цена со скидкой» → «Минимальная».

    Незаполненные и не понижающие колонки выбрасываем: у большинства товаров
    средней ступени нет, и лестница остаётся двухступенчатой, как была.
    """
    rungs: list[int] = []
    for value in (
        getattr(product, "price", None),
        getattr(product, "discount_price", None),
        getattr(product, "min_price", None),
    ):
        if value is None:
            continue
        step = int(value)
        if not rungs or step < rungs[-1]:
            rungs.append(step)
    return rungs


def _next_concession(rungs: list[int], already_quoted: int | None) -> int | None:
    """Ступень ниже той, что клиент уже слышал.

    Скидочный скрипт прыгал с 5 990 ₽ сразу на 4 990 ₽, потому что подставлял
    нижнюю границу. Теперь спуск идёт по одной ступени за возражение, а на дне
    лестницы остаётся дно — ниже уступать нечем.
    """
    if not rungs:
        return None
    if already_quoted is None:
        # Цену ещё не называли, а скрипт уже уступает. Такого в регламенте нет,
        # но если случилось — отдаём вторую ступень, а не дно.
        return rungs[1] if len(rungs) > 1 else rungs[0]
    lower = [r for r in rungs if r < already_quoted]
    return lower[0] if lower else min(rungs[-1], already_quoted)


def _pin_price(dialog, product_name: str, price):
    """Цена этого товара для этого диалога: уже названная либо новая.

    Матрица — источник правды, пока цену не произнесли вслух. После этого правка
    матрицы не должна доезжать до клиента, с которым уже договорились: 10 августа
    прайс поправили в 12:25, и диалог 142, где в 09:56 согласовали 4 990 ₽, в
    13:15 получил счёт на 5 990 ₽.

    Понизить можно — это уступка при возражении, ради неё существует
    «[минимальная-цена:]». Поднять нельзя ни при каких условиях.
    """
    if price is None or dialog is None or not product_name:
        return price
    pinned = (dialog.quoted_prices or {}).get(product_name)
    value = int(price)
    if pinned is not None and value > int(pinned):
        logger.info(
            "цена диалога %s зафиксирована: товар %r, матрица %s, отдаём %s",
            dialog.id, product_name, value, int(pinned),
        )
        return int(pinned)
    if pinned is None or value < int(pinned):
        # dict пересобираем целиком: SQLAlchemy не увидит мутацию вложенного
        # словаря в JSON-колонке и не запишет изменение.
        dialog.quoted_prices = {**(dialog.quoted_prices or {}), product_name: value}
    return value


async def _price_script_ids(db: AsyncSession) -> set[int]:
    """Скрипты, которыми мы называем клиенту РАСЧЁТ.

    Узнаются по плейсхолдеру цены в тексте — «Стоимость толстовки … [цена:свитшот]»,
    «Специально для Вас … [минимальная-цена:свитшот]». Плюс их варианты под
    рекламные метки: у комплекта (скрипт 519 при 367) цены выписаны числами, и по
    тексту его от обычного сообщения не отличить, а по ссылке `variant_of_script_id`
    — сразу.

    Скрипт оформления в набор не попадает: в нём стоит «[сумма-заказа:…]», а не
    «[цена:…]». Это важно — иначе он считал бы сумму по собственному прошлому
    сообщению и навсегда закреплял бы свою же ошибку.
    """
    from sqlalchemy import or_, select

    from app.db.models import Script

    base = (await db.execute(
        select(Script.id).where(
            Script.is_active == True,
            or_(*[
                Script.phrase_text.like(f"%[{macro}:%")
                for macro in ("цена", "цена-до-скидки", "цена-со-скидкой", "минимальная-цена")
            ]),
        )
    )).scalars().all()
    if not base:
        return set()
    variants = (await db.execute(
        select(Script.id).where(
            Script.is_active == True,
            Script.variant_of_script_id.in_(base),
        )
    )).scalars().all()
    return set(base) | set(variants)


async def _quoted_order_total(db: AsyncSession, dialog) -> int | None:
    """Сумма из последнего РАСЧЁТА, отправленного клиенту.

    Якорь — именно ценовой скрипт, а не любое наше сообщение с цифрой. В диалоге
    83014 клиент после расчёта спросил про жилетку, ИИ ответил «её стоимость
    4 090 ₽», и «последняя названная цена» превратила бы заказ на комплект
    (8 980 ₽) в заказ на безрукавку.

    Рассылки не читаем: цена в них своя («ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА» ушла в
    58 тысяч диалогов) и к заказу отношения не имеет. Недоставленное тоже: его
    клиент не видел, а строка в базе остаётся (см. app.vk.outgoing).
    """
    if dialog is None:
        return None
    from sqlalchemy import select

    from app.db.models import Message, MessageRole
    from app.vk.outgoing import was_delivered

    rows = (await db.execute(
        select(Message)
        .where(
            Message.dialog_id == dialog.id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(40)
    )).scalars().all()
    ours = [
        m for m in rows
        if was_delivered(m) and not (m.msg_metadata or {}).get("broadcast")
    ]

    price_ids = await _price_script_ids(db)
    for m in ours:
        if (m.msg_metadata or {}).get("source_script_id") in price_ids:
            total = order_total([m.text or ""])
            if total is not None:
                return total

    # Расчёта скриптом не было — значит диалог считал человек, и его сумму по
    # тексту не восстановить. Первая версия правки брала тут последнюю названную
    # цену и в диалоге 82426 подставила «Остаток составляет 8080 руб» — остаток
    # после предоплаты, а не сумму заказа. Возвращаемся к цене матрицы: она
    # хотя бы предсказуема, а такие диалоги ИИ и не оформляет — они на паузе.
    return None


async def render_price_placeholders(
    db: AsyncSession, text: str, type_id: int | None = None, dialog=None,
) -> str:
    """Подставить акционные цены товаров вместо «[цена:запрос]».

    Товар не нашёлся — плейсхолдер убираем вместе со скобками, оставив запрос
    как обычное слово: лучше фраза без цифры, чем «[цена:свитшот]» у клиента.

    `dialog` — диалог, в который уйдёт текст. Передан: цена товара закрепляется
    за диалогом и больше не растёт (см. _pin_price). Не передан (например,
    предпросмотр скрипта в админке): отдаём текущую цену матрицы.
    """
    text = _render_payment_link(text or "")
    matches = list(_PRICE_PLACEHOLDER_RE.finditer(text))
    if not matches:
        return text

    svc = ProductService(db)
    result = text
    for m in matches:
        macro = m.group(1).lower()
        query = m.group(2).strip()

        # Итог заказа считается по переписке и от товарной матрицы не зависит:
        # клиент с метки на комплект видел свою сумму (5 490 + 3 490 = 8 980 ₽),
        # а матрица знает только цену одного изделия. Товар в скобках — запасной
        # вариант, если цену ещё не называли: черновик в админке, тестовый диалог,
        # оборванный ход.
        if macro == "сумма-заказа":
            total = await _quoted_order_total(db, dialog)
            if total is not None:
                logger.info(
                    "сумма заказа взята из переписки: %s | dialog=%s",
                    total, getattr(dialog, "id", None),
                )
                result = result.replace(m.group(0), format_price(total))
                continue

        # limit=1 нельзя: LIMIT отсекает строки в SQL, до сортировки «точное
        # название вперёд» (см. ProductService.search), и «[цена:Доп. принт]»
        # доставал градиентный принт.
        products = await svc.search(query, type_id=type_id, limit=5)
        price = None
        if products:
            p = products[0]
            rungs = price_ladder(p)
            if macro == "минимальная-цена":
                quoted = (getattr(dialog, "quoted_prices", None) or {}).get(p.name)
                price = _next_concession(rungs, int(quoted) if quoted is not None else None)
            elif macro == "цена-со-скидкой":
                price = rungs[1] if len(rungs) > 1 else (rungs[0] if rungs else None)
            else:
                price = rungs[0] if rungs else None
            price = _pin_price(dialog, p.name, price)
        if price is None:
            logger.warning("price placeholder %r: товар не найден, убираю плейсхолдер", query)
            result = result.replace(m.group(0), query)
        else:
            result = result.replace(m.group(0), format_price(price))
    return result
