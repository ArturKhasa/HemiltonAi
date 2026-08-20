"""Agent-callable tools injected via openai-agents SDK function_tool."""
import logging
import re

from agents import function_tool

from app.sales.scripts import ScriptService
from app.sales.products import ProductService
from app.sales.embeddings import find_similar
from app.db.session import AsyncSessionLocal
from app.vk.spintax import resolve_spintax

logger = logging.getLogger(__name__)


async def get_script_phrase_text(
    script_id: int, type_id: int | None = None, dialog_id: int | None = None,
) -> str:
    """Текст скрипта из БД с раскрытым spintax и подставленными плейсхолдерами.

    Цена и ссылка на оплату подставляются здесь, а не оставляются модели: увидев
    «[цена:свитшот]», она просто выбрасывала плейсхолдер и называла цифру из
    головы — 4 990 ₽ рядом со скриптовыми 5 990 ₽ в том же ходу (диалог 44), а
    «[ссылка-оплаты]» превращалась в «вот счёт-ссылка на 500 рублей:» без самой
    ссылки (диалог 40).

    dialog_id нужен, чтобы модель увидела ту же цену, что уже названа клиенту:
    иначе она перепишет её в reply_text из своего черновика, и правка матрицы
    посреди диалога снова доедет до клиента (см. _pin_price).
    """
    from app.db.models import Dialog
    from app.sales.price_placeholder import render_price_placeholders

    async with AsyncSessionLocal() as db:
        script = await ScriptService(db).get_by_id(script_id)
        if not script or not (script.phrase_text or "").strip():
            return f"Скрипт {script_id} не найден или не содержит текста."
        dialog = await db.get(Dialog, dialog_id) if dialog_id else None
        text = await render_price_placeholders(
            db, resolve_spintax(script.phrase_text),
            type_id=type_id if type_id is not None else script.type_id,
            dialog=dialog,
        )
        # У инструмента своя сессия: закреплённую цену нужно сохранить здесь,
        # иначе первый же черновик потеряет её и следующий вызов посчитает
        # цену заново.
        if dialog is not None:
            await db.commit()
        return text


def make_get_script_phrase(type_id: int | None, dialog_id: int | None = None):
    """Return a get_script_phrase tool scoped to a specific dialog type."""
    @function_tool
    async def get_script_phrase(script_id: int) -> str:
        """Fetch the ready-to-send phrase text of a script by its script_id. Prices and the
        payment link are already substituted — copy the returned numbers and links exactly,
        never replace them with your own. Use the text as the basis for reply_text and set
        source_script_id to this script_id in the final output.
        """
        logger.info("[tool] get_script_phrase called | script_id=%d", script_id)
        text = await get_script_phrase_text(script_id, type_id, dialog_id)
        logger.info("[tool] get_script_phrase done | script_id=%d | text_len=%d", script_id, len(text))
        return text
    return get_script_phrase


async def save_client_marketing_tags(client_id: int, tags: list[str]) -> None:
    """Persist the marketing tag list onto the clients row (by primary key)."""
    from sqlalchemy import update
    from app.db.models import Client
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Client).where(Client.id == client_id).values(marketing_tags=tags)
            )
            await db.commit()
    except Exception as e:
        logger.warning("[tool] save marketing_tags failed | client_id=%s | error=%s", client_id, e)


async def fetch_client_tags(client_id: int | None) -> set[str] | None:
    """Маркетинговые теги клиента из локальной БД, None если клиент неизвестен
    или теги никогда не проставлялись (NULL — фильтрация скриптов не применяется)."""
    if client_id is None:
        return None
    from sqlalchemy import select
    from app.db.models import Client
    async with AsyncSessionLocal() as db:
        tags = await db.scalar(select(Client.marketing_tags).where(Client.id == client_id))
    if tags is None:
        return None
    return {norm_tag(str(t)) for t in tags if str(t).strip()}


def norm_tag(tag: str) -> str:
    """Метка в сравнимом виде: «#SweetGold» и «sweetgold» — одно и то же.

    В скрипте её пишет человек, а к клиенту она приезжает из рекламной ссылки —
    регистр и решётка не совпадают почти никогда. Пинги так сравнивают давно
    (см. ping.worker._resolve_marketing_tag), скрипты сравнивали побуквенно: под
    меткой с другим регистром клиент молча получал общий расчёт вместо своего.
    """
    return tag.strip().lstrip("#").upper()


def _parse_tags(raw: str | None) -> set[str]:
    """scripts.marketing_tag holds one or more comma-separated tags ('СУПЕРГЕРОИ, ДЕТИ СУПЕРГЕРОИ')."""
    return {norm_tag(t) for t in (raw or "").split(",") if t.strip()}


# Семейства товаров. Клиент 44731492 покупал толстовку, попросил показать, как
# она выглядит, и получил скрипт 406 — «Этот костюм мы отшиваем в 4-х цветах»
# с фотографиями костюма (07:54). Скрипт лежит на стадии None, то есть виден
# всегда, и по условию «Дополнительные фотографии изделий» подходит под любой
# запрос показать товар.
#
# Свитшот, толстовка и худи — одно семейство: в скриптах ОП эти слова стоят
# вперемешку про одну и ту же вещь («Стоимость толстовки» в ветке свитшота).
_PRODUCT_FAMILIES = {
    "кофта": ("свитшот", "толстовк", "худи", "кофт"),
    "костюм": ("костюм",),
    "футболка": ("футболк",),
    "лонгслив": ("лонгслив",),
    "жилетка": ("жилетк",),
    "кепка": ("кепк",),
}

# Линейка воронки: приветствие обещает толстовку, прайс считает свитшот, палитра
# показывает кофты. Пока клиент сам не назвал другой товар, разговор идёт про
# них — иначе на «интересно, как это выглядит» уходят фотографии костюма
# (диалог 1847, 20.08: скрипт 406 «Этот костюм мы отшиваем в 4-х цветах»,
# уверенность 0.99). Клиент написал «костюм» — семейство сменится само.
DEFAULT_PRODUCT_FAMILY = "кофта"

# Допродажа НАРОЧНО говорит о другом товаре: «предлагаю добавить футболку»
# уместно в диалоге про толстовку, и отсекать такие скрипты нельзя.
_UPSELL_RE = re.compile(r"доп\.|допрод|второе издели|комплект|в подарок", re.IGNORECASE)


def _families(text: str | None) -> set[str]:
    lowered = (text or "").lower().replace("ё", "е")
    return {
        family for family, stems in _PRODUCT_FAMILIES.items()
        if any(stem in lowered for stem in stems)
    }


def client_product_family(product: str | None) -> str | None:
    """Семейство товара, который выбрал клиент («свитшот» → «кофта»)."""
    families = _families(product)
    return next(iter(families)) if len(families) == 1 else None


def _norm_condition(s) -> str:
    """Conditions are hand-typed in the админка — collapse whitespace (tabs/newlines) for comparison."""
    return " ".join(str(getattr(s, "condition", "") or "").split())


# Стадии, которые начинаются ПОСЛЕ подтверждённой оплаты. Пока оплаты нет, эти
# шаги для модели не существуют: она отправила «Благодарю Вас за заказ и за
# доверие! Теперь пришлите адрес пункта выдачи СДЭК» клиенту, не заплатившему ни
# рубля (диалог 142, 14:13). ОП, 14:15: «Оплаты от клиента не было».
PAID_ONLY_STAGES = frozenset({"post_payment", "paid"})


def format_scripts_list(
    scripts,
    client_tags: set[str] | None,
    current_stage: str | None = None,
    exclude_script_ids: set[int] | None = None,
    client_product: str | None = None,
    payment_confirmed: bool = True,
) -> str:
    """Filter scripts by the client's marketing tags + current funnel stage, render the output.

    Tag semantics:
    - Only tags described in the админке (= mentioned by at least one script of this
      type) count; any other client tag is ignored, so a client with only unknown
      tags is treated as untagged.
    - A tagged script matches when ALL its tags are present on the client (AND) —
      combo scripts ('СУПЕРГЕРОИ, ДЕТИ СУПЕРГЕРОИ') need both. Untagged scripts always match.
    - Most specific wins: among matching scripts with the same condition, only those
      with the max tag count are kept (combo > single > untagged) — otherwise the model
      picks an arbitrary duplicate.
    - tags unknown (None): show everything, no filtering.

    Funnel-stage gate (only when current_stage is set): a script with a concrete
    funnel_stage is shown only on exactly that stage — past-stage scripts pull the
    dialog backwards, future-stage ones jump it forward. funnel_stage=None is always
    kept — recovery/Q&A scripts valid at any stage.

    exclude_script_ids — scripts already sent to this client (e.g. the previous AI
    reply's source_script_id) are hidden entirely, so the model physically can't
    send the same phrase twice in a row.
    """
    # Отправляет только человек: макет с правками кидают дизайнеры своими руками
    # (ОП, 10 августа, 14:15). Модели такие скрипты не показываем вовсе.
    scripts = [s for s in scripts if not getattr(s, "manual_only", False)]

    # Шаги «после оплаты» — только после подтверждённой оплаты.
    if not payment_confirmed:
        scripts = [
            s for s in scripts
            if getattr(s, "funnel_stage", None) not in PAID_ONLY_STAGES
        ]

    if client_tags is not None:
        known_tags: set[str] = set()
        for s in scripts:
            known_tags |= _parse_tags(s.marketing_tag)
        effective_tags = client_tags & known_tags
        # Untagged scripts (empty set) are a subset of anything — always kept.
        scripts = [s for s in scripts if _parse_tags(s.marketing_tag) <= effective_tags]
    # client_tags is None (unknown): show everything, don't filter

    if current_stage:
        scripts = [
            s
            for s in scripts
            if getattr(s, "funnel_stage", None) is None
            or s.funnel_stage == current_stage
        ]

    if client_tags is not None:
        # Most specific wins within one condition (after the stage gate, so only
        # actually visible scripts compete).
        max_tags_by_cond: dict[str, int] = {}
        for s in scripts:
            cond = _norm_condition(s)
            n = len(_parse_tags(s.marketing_tag))
            max_tags_by_cond[cond] = max(max_tags_by_cond.get(cond, 0), n)
        scripts = [
            s for s in scripts
            if len(_parse_tags(s.marketing_tag)) == max_tags_by_cond[_norm_condition(s)]
        ]

    # Скрипт про другой товар клиенту, который уже выбрал вещь, показывать
    # нечего: он не «дополнительное фото», а другой товар целиком.
    family = client_product_family(client_product) or DEFAULT_PRODUCT_FAMILY
    if family:
        kept = []
        for s in scripts:
            if _UPSELL_RE.search(_norm_condition(s) or ""):
                kept.append(s)
                continue
            about = _families(s.phrase_text) | _families(_norm_condition(s))
            if about and family not in about:
                continue
            kept.append(s)
        scripts = kept

    lines = []
    for s in scripts:
        if exclude_script_ids and s.id in exclude_script_ids:
            continue  # эта фраза только что была отправлена — дубль смысла
        lines.append(
            f"script_id={s.id}"
            + (f" | tag={s.marketing_tag}" if s.marketing_tag else "")
            + f" | condition: {_norm_condition(s)}"
        )
    if not lines:
        return "No scripts configured."
    return "Доступные скрипты:\n" + "\n".join(lines)


def make_list_scripts(
    type_id: int | None,
    client_id: int | None = None,
    current_stage: str | None = None,
    exclude_script_ids: set[int] | None = None,
    client_product: str | None = None,
    payment_confirmed: bool = True,
):
    """Return a list_scripts tool scoped to a specific dialog type.

    If client_id is given, scripts are filtered by the client's local marketing_tags
    (see format_scripts_list: AND-match on all script tags, unknown client tags ignored,
    most specific script wins per condition; untagged scripts always shown).

    current_stage (the dialog's detected funnel step) gates staged scripts to exactly
    that step; None-stage scripts are always kept.

    exclude_script_ids — script IDs the model must not reuse (already sent to this
    client); they never appear in the tool output.
    """
    @function_tool
    async def list_scripts() -> str:
        """Return active scripts with their conditions and script IDs.
        Match the client's situation to the best condition, then call get_script_phrase
        with the script_id to fetch the ready-to-send phrase text.

        If the client has a marketing tag, only scripts for that tag are shown.
        """
        logger.info("[tool] list_scripts called | type_id=%s", type_id)
        async with AsyncSessionLocal() as db:
            svc = ScriptService(db)
            scripts = await svc.get_all_active(type_id=type_id)

        client_tags = await fetch_client_tags(client_id)
        logger.info(
            "[tool] list_scripts done | type_id=%s | total=%d | client_tags=%s | stage=%s | excluded=%s",
            type_id, len(scripts), sorted(client_tags) if client_tags is not None else None,
            current_stage, sorted(exclude_script_ids) if exclude_script_ids else None,
        )
        return format_scripts_list(
            scripts, client_tags, current_stage=current_stage,
            exclude_script_ids=exclude_script_ids, client_product=client_product,
            payment_confirmed=payment_confirmed,
        )
    return list_scripts


# «Товары не найдены» агент читал как «такого товара нет в продаже» и сообщал
# клиенту, что позиция закончилась (диалог 9 на проде: «чёрные худи закончились»
# при живом остатке). Пустой результат поиска — факт о запросе, а не о складе,
# и формулировка обязана это проговаривать.
_NO_PRODUCTS_FOUND = (
    "Поиск по этому запросу ничего не дал. Попробуй ещё раз одним словом "
    "(например «свитшот» или «худи»). ЭТО НЕ ЗНАЧИТ, ЧТО ТОВАРА НЕТ: о наличии, "
    "отсутствии и ценах клиенту не сообщай, пока товар не найден."
)


async def run_product_search(query: str, type_id: int | None) -> str:
    """Текст ответа инструмента search_products. Общая реализация для
    openai-agents тулзы и anthropic_runner."""
    async with AsyncSessionLocal() as db:
        svc = ProductService(db)
        products = await svc.search(query, type_id=type_id)
        if products:
            return format_products_list(products)
        widest, loose = await svc.search_loose(query, type_id=type_id)
    if not loose:
        return _NO_PRODUCTS_FOUND
    # Расширенный поиск помечаем явно: иначе агент выдаёт находку по одному слову
    # за точный ответ на весь запрос.
    return (
        f"Точного совпадения по запросу «{query}» нет. "
        f"Вот что нашлось по слову «{widest}» — сверься, подходит ли:\n"
        + format_products_list(loose)
    )


def format_products_list(products) -> str:
    if not products:
        return _NO_PRODUCTS_FOUND
    # Нижние ступени лестницы модели не показываем вовсе. Раньше рядом с ценой
    # стояла «(акционная: 4 990₽)», и модель называла её сама, своими словами:
    # в диалоге 162 клиент за три минуты услышал «Свитшот - 4 990 ₽ по акции» и
    # «Стоимость толстовки - 5 990 ₽» про одну и ту же вещь. Уступку выдаёт
    # только скрипт отработки возражения, через «[минимальная-цена:]», и ровно
    # на одну ступень (см. app.sales.price_placeholder).
    lines = []
    for p in products:
        price = f"{p.price:g}₽" if p.price is not None else "?"
        size = f" | размерная сетка: {p.size_chart}" if p.size_chart else ""
        lines.append(f"- {p.name}: {price}{size}")
    return "\n".join(lines)


def make_search_products(type_id: int | None):
    """Return a search_products tool scoped to a specific dialog type.

    Товарная матрица отдельно от list_scripts: тут только факты (цена, сетка, фото),
    без готовых формулировок — финальный текст клиенту агент строит сам.
    """
    @function_tool
    async def search_products(query: str) -> str:
        """Найти товары по названию — например "свитшот", "худи", "чёрный свитшот".
        Порядок слов и род прилагательного значения не имеют. Возвращает цену,
        акционную цену (если есть) и размерную сетку. Вызывай ОБЯЗАТЕЛЬНО перед тем,
        как назвать клиенту цену, размерную сетку или сказать что-либо о наличии
        товара, если в list_scripts() нет готовой фразы с этой информацией.

        Пустой результат означает, что не подошёл запрос, а НЕ что товара нет в
        наличии. В этом случае переспроси одним словом и ни в коем случае не
        сообщай клиенту, что позиция закончилась.

        А вот если по слову «свитшот» товары нашлись, а с названным цветом среди
        них нет — цвета действительно нет. Так и скажи прямо и перечисли те, что
        есть; «уточню в каталоге» вместо ответа клиенту не пиши.
        """
        logger.info("[tool] search_products called | type_id=%s | query=%r", type_id, query)
        result = await run_product_search(query, type_id)
        logger.info(
            "[tool] search_products done | type_id=%s | query=%r | found=%s",
            type_id, query, not result.startswith(_NO_PRODUCTS_FOUND[:20]),
        )
        return result
    return search_products


def make_get_product_photo(type_id: int | None):
    """Return a get_product_photo tool scoped to a specific dialog type."""
    @function_tool
    async def get_product_photo(product_name: str) -> str:
        """Найти фото товара по названию (см. search_products) и получить токен для
        вставки в reply_text. Скопируй результат буквально в текст ответа клиенту —
        при отправке система сама превратит его в настоящее фото-вложение. Не
        вставляй сырой URL фото в reply_text без этого токена.

        Ответ «Фото не найдено» означает именно это: фото нет. Токен в таком
        случае НЕ ВЫДУМЫВАЙ — «[photo-фиолетовый свитшот]» уходит клиенту
        битым вложением (замечание ОП от 6 августа)."""
        logger.info("[tool] get_product_photo called | type_id=%s | product_name=%r", type_id, product_name)
        async with AsyncSessionLocal() as db:
            products = await ProductService(db).search(product_name, type_id=type_id, limit=5)
        if not products or not products[0].photo_url:
            return "Фото не найдено для этого товара."
        return f"[photo-{products[0].photo_url}]"
    return get_product_photo


def format_similar_examples(rows) -> str:
    if not rows:
        return "Похожих примеров не найдено."
    lines = []
    for r in rows:
        lines.append(f"Клиент: {r.client_text}\nМенеджер: {r.manager_text}")
    return "\n---\n".join(lines)


def make_find_similar_examples(type_id: int | None):
    """Return a find_similar_examples tool scoped to a specific dialog type."""
    @function_tool
    async def find_similar_examples(query: str) -> str:
        """Найти похожие вопросы клиентов из реальных диалогов и как на них отвечал
        менеджер — семантический поиск, не точное совпадение. Используй как референс
        тона и аргументации для нестандартных вопросов, на которые нет готового
        скрипта в list_scripts(). НЕ копируй найденный ответ дословно — только
        подход и аргументы, текст строй сам по правилам тона из промпта.
        """
        logger.info("[tool] find_similar_examples called | type_id=%s | query=%r", type_id, query)
        if type_id is None:
            return "Направление не определено."
        async with AsyncSessionLocal() as db:
            rows = await find_similar(db, type_id, query)
        return format_similar_examples(rows)
    return find_similar_examples

async def tagged_variant(db, script, client_tags: set[str] | None):
    """Тот же шаг воронки, но в версии под метку клиента.

    Скрипты воронки связаны фиксированным `follow_up_script_id`, а расчёт под
    разные рекламные метки бывает разный: на «sweetgold» одна цена, на
    «sweetrussia» другая. Модель такую замену делает сама (см. фильтр по тегам
    в list_scripts), а связка шла по id и всегда отправляла общий вариант.

    Берём среди активных скриптов того же типа те, у кого совпадает условие, и
    выбираем самый специфичный из подходящих клиенту. Не нашли — исходный.
    """
    if not client_tags:
        return script
    client_tags = {norm_tag(str(t)) for t in client_tags if str(t).strip()}
    from sqlalchemy import select as _select

    from app.db.models import Script as _Script

    rows = await db.execute(
        _select(_Script).where(
            _Script.is_active == True,
            _Script.type_id == script.type_id,
        )
    )
    cond = _norm_condition(script)
    candidates = [
        s for s in rows.scalars().all()
        if _norm_condition(s) == cond and _parse_tags(s.marketing_tag) <= client_tags
    ]
    if not candidates:
        return script
    return max(candidates, key=lambda s: (len(_parse_tags(s.marketing_tag)), -s.id))
