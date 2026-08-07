"""Плейсхолдер цены в текстах скриптов: «[цена:свитшот]» → «4 990 ₽».

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

from app.sales.products import ProductService

logger = logging.getLogger(__name__)

# «[цена:свитшот]» — акционная (то, что клиент платит сегодня),
# «[цена-до-скидки:свитшот]» — обычная, та самая «вместо N рублей».
_PRICE_PLACEHOLDER_RE = re.compile(
    r"\[цена(-до-скидки)?:([^\]]+)\]", re.IGNORECASE
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


async def render_price_placeholders(
    db: AsyncSession, text: str, type_id: int | None = None,
) -> str:
    """Подставить акционные цены товаров вместо «[цена:запрос]».

    Товар не нашёлся — плейсхолдер убираем вместе со скобками, оставив запрос
    как обычное слово: лучше фраза без цифры, чем «[цена:свитшот]» у клиента.
    """
    text = _render_payment_link(text or "")
    matches = list(_PRICE_PLACEHOLDER_RE.finditer(text))
    if not matches:
        return text

    svc = ProductService(db)
    result = text
    for m in matches:
        before_discount = bool(m.group(1))
        query = m.group(2).strip()
        # limit=1 нельзя: LIMIT отсекает строки в SQL, до сортировки «точное
        # название вперёд» (см. ProductService.search), и «[цена:Доп. принт]»
        # доставал градиентный принт.
        products = await svc.search(query, type_id=type_id, limit=5)
        price = None
        if products:
            p = products[0]
            price = p.price if before_discount else (p.min_price if p.min_price is not None else p.price)
        if price is None:
            logger.warning("price placeholder %r: товар не найден, убираю плейсхолдер", query)
            result = result.replace(m.group(0), query)
        else:
            result = result.replace(m.group(0), format_price(price))
    return result
