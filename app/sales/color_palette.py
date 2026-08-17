"""Вопрос про цвет всегда уходит с картинкой-палитрой.

Лена, 17.08: «С вопросом про выбор цвета обязательно нужно картинку отправлять
клиенту». Картинка есть — она лежит в скриптах «3. Цвет СВИТШОТА» (по умолчанию)
и «3. Цвет ХУДИ», — но за неделю все 65 вопросов про цвет оказались репликами
модели, а не скриптами: скрипт она пересказывает своими словами. В 32 случаях
токен `[photo-…]` из текста скрипта переехал в ответ вместе с текстом, в
остальных 33 клиент получил вопрос без палитры и выбирал цвет вслепую.

Поэтому палитру подставляет код: спросили про цвет, картинки в ответе нет —
берём её из активного скрипта цвета для того изделия, которое обсуждает клиент.
"""
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Script

logger = logging.getLogger(__name__)

_PHOTO_TOKEN_RE = re.compile(r"\[photo-[^\]]+\]")

# «а цвет для свитшота какой выберем?», «Какой цвет выбираете?», «цвет белый или
# чёрный?». Подтверждение цвета («Чёрный цвет зафиксировала») под правило не
# попадает: там нет ни вопроса о выборе, ни вопросительного знака в этой фразе.
_ASKS_COLOR_RE = re.compile(
    r"как\w*\s+(?:именно\s+)?цвет"
    r"|цвет\w*\s+(?:для\s+\w+\s+)?(?:как\w+\s+)?"
    r"(?:выбер|выбира|возьм|подойд|нужен|нужна|хотите|нравится|предпочит)"
    r"|цвет\w*\s*[-—:]?\s*(?:белый|чёрный|черный|бежевый)\s+или",
    re.I,
)

# Изделие, для которого нужна палитра: у худи и толстовки с капюшоном своя.
_HOODIE_RE = re.compile(r"худи|капюшон|толстовк", re.I)
# Условие скрипта палитры в админке: «3. Цвет СВИТШОТА» / «3. Цвет ХУДИ».
_COLOR_SCRIPT_RE = re.compile(r"цвет\s+(свитшот|худи)", re.I)


def asks_color(text: str) -> bool:
    """Реплика спрашивает у клиента цвет."""
    return any(
        "?" in s and _ASKS_COLOR_RE.search(s)
        for s in re.split(r"(?<=[.!?…])\s+|\n+", text or "")
    )


def has_photo(text: str) -> bool:
    return bool(_PHOTO_TOKEN_RE.search(text or ""))


async def palette_token(
    db: AsyncSession, type_id: int | None, product: str | None,
) -> str | None:
    """Токен картинки с палитрой для изделия клиента, либо None.

    Изделие берём из [Уже собрано]; не назвал — палитра свитшота, как и сам
    скрипт по умолчанию.
    """
    q = select(Script).where(Script.is_active == True)
    if type_id is not None:
        q = q.where(Script.type_id == type_id)
    scripts = [
        s for s in (await db.execute(q.order_by(Script.id))).scalars().all()
        if _COLOR_SCRIPT_RE.search(s.condition or "")
    ]
    if not scripts:
        return None

    wants_hoodie = bool(product and _HOODIE_RE.search(product))
    for script in scripts:
        is_hoodie = "худи" in (script.condition or "").lower()
        if is_hoodie != wants_hoodie:
            continue
        token = _PHOTO_TOKEN_RE.search(script.phrase_text or "")
        if token:
            return token.group(0)
    return None


async def with_palette(
    db: AsyncSession,
    text: str,
    type_id: int | None,
    product: str | None,
    ctx: str = "",
) -> str:
    """Добавить палитру к вопросу о цвете, если её там нет."""
    if not asks_color(text) or has_photo(text):
        return text
    token = await palette_token(db, type_id, product)
    if not token:
        logger.warning("[%s] вопрос про цвет без палитры: скрипт цвета не найден", ctx)
        return text
    logger.info("[%s] к вопросу про цвет добавлена палитра", ctx)
    return f"{text.rstrip()}\n\n{token}"
