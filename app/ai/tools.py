"""Agent-callable tools injected via openai-agents SDK function_tool."""
import logging

from agents import function_tool

from app.sales.scripts import ScriptService
from app.sales.products import ProductService
from app.sales.embeddings import find_similar
from app.db.session import AsyncSessionLocal
from app.vk.spintax import resolve_spintax

logger = logging.getLogger(__name__)


async def get_script_phrase_text(script_id: int) -> str:
    """Текст скрипта из БД с раскрытым spintax. Общая реализация для
    openai-agents тулзы и anthropic_runner."""
    async with AsyncSessionLocal() as db:
        script = await ScriptService(db).get_by_id(script_id)
    if not script or not (script.phrase_text or "").strip():
        return f"Скрипт {script_id} не найден или не содержит текста."
    return resolve_spintax(script.phrase_text)


@function_tool
async def get_script_phrase(script_id: int) -> str:
    """Fetch the ready-to-send phrase text of a script by its script_id. Resolves spintax
    automatically. Use the returned text as the basis for reply_text and set
    source_script_id to this script_id in the final output.
    """
    logger.info("[tool] get_script_phrase called | script_id=%d", script_id)
    text = await get_script_phrase_text(script_id)
    logger.info("[tool] get_script_phrase done | script_id=%d | text_len=%d", script_id, len(text))
    return text


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
    return set(tags)


def _parse_tags(raw: str | None) -> set[str]:
    """scripts.marketing_tag holds one or more comma-separated tags ('СУПЕРГЕРОИ, ДЕТИ СУПЕРГЕРОИ')."""
    return {t.strip() for t in (raw or "").split(",") if t.strip()}


def _norm_condition(s) -> str:
    """Conditions are hand-typed in the админка — collapse whitespace (tabs/newlines) for comparison."""
    return " ".join(str(getattr(s, "condition", "") or "").split())


def format_scripts_list(
    scripts,
    client_tags: set[str] | None,
    current_stage: str | None = None,
    exclude_script_ids: set[int] | None = None,
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
            exclude_script_ids=exclude_script_ids,
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
    lines = []
    for p in products:
        price = f"{p.price:g}₽" if p.price is not None else "?"
        min_price = f" (акционная: {p.min_price:g}₽)" if p.min_price is not None else ""
        size = f" | размерная сетка: {p.size_chart}" if p.size_chart else ""
        lines.append(f"- {p.name}: {price}{min_price}{size}")
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
        вставляй сырой URL фото в reply_text без этого токена."""
        logger.info("[tool] get_product_photo called | type_id=%s | product_name=%r", type_id, product_name)
        async with AsyncSessionLocal() as db:
            products = await ProductService(db).search(product_name, type_id=type_id, limit=1)
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
