"""Шаги воронки ОП1, которые обязаны уйти клиенту независимо от решения модели.

Регламент ОП описывает воронку как лестницу: «2. Похвала» уходит связкой вместе
с «2.2 Стоимость» и «2.3 Доставка», ссылка на оплату — сразу после того, как
клиент дал ФИО и телефон. Связки разворачивает runner по follow_up_script_id,
но точка входа в связку до сих пор зависела от того, поставит ли модель
source_script_id.

На проде она его не поставила (диалог 52, ai_run 565): вместо скрипта «2. Похвала»
модель написала свой пересказ «Супер, зафиксировала «Соколова»», связка не
развернулась, цена не ушла — и дальше семь ходов подряд она спрашивала «какой
дизайн нанесём на кофту?», потому что без цены в истории стадия зажата в greeting.
Промптом это чинить бессмысленно: пропущенный шаг воронки — не вопрос
формулировки, а вопрос того, ушло сообщение или нет.
"""
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageRole, Script

logger = logging.getLogger(__name__)

# «2. Похвала» — присоединение после ответа на вопрос про имя/фамилию. Именно с
# него начинается связка «похвала → стоимость → доставка».
_PRAISE_CONDITION_RE = re.compile(r"похвал", re.I)

# «5.2 Ссылка на оплату» — единственный скрипт стадии payment_link со ссылкой.
_PAYMENT_LINK_CONDITION_RE = re.compile(r"ссылк\w*\s+на\s+оплату", re.I)

# Все платёжные ссылки проекта содержат «pay» в URL (monro-book-payment.online,
# параметр ?pay=1000, заглушка example.com/pay/500); фото и CDN-ссылки — нет.
PAYMENT_LINK_RE = re.compile(r"https?://\S*pay", re.IGNORECASE)


async def _pick(db: AsyncSession, type_id: int | None, pattern: re.Pattern) -> Script | None:
    """Наименьший по id активный скрипт, чьё условие совпало с шаблоном.
    Наименьший — чтобы выбор был воспроизводимым: в выгрузке ОП условия
    дублируются под разные варианты товара."""
    q = select(Script).where(Script.is_active == True)
    if type_id is not None:
        q = q.where(Script.type_id == type_id)
    rows = (await db.execute(q.order_by(Script.id))).scalars().all()
    for s in rows:
        if pattern.search(s.condition or "") and (s.phrase_text or "").strip():
            return s
    return None


async def find_praise_script(db: AsyncSession, type_id: int | None) -> Script | None:
    return await _pick(db, type_id, _PRAISE_CONDITION_RE)


async def find_payment_link_script(db: AsyncSession, type_id: int | None) -> Script | None:
    return await _pick(db, type_id, _PAYMENT_LINK_CONDITION_RE)


async def dialog_has_payment_link(db: AsyncSession, dialog_id: int) -> bool:
    """Ссылка на оплату уже уходила клиенту в этом диалоге.

    Сверяем в Python, а не regexp-оператором СУБД: шаблон один и тот же и для
    истории, и для свежего ответа модели, а диалог короткий.
    """
    rows = await db.execute(
        select(Message.text).where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
    )
    return any(PAYMENT_LINK_RE.search(t or "") for (t,) in rows.all())


async def answered_inscription_question(db: AsyncSession, dialog_id: int) -> bool:
    """Последнее наше сообщение — вопрос воронки про имя/фамилию для нанесения.

    Значит текущая реплика клиента и есть ответ на него, а следом по регламенту
    обязаны уйти похвала, стоимость и доставка.
    """
    from app.sales.order_slots import ASKS_INSCRIPTION_RE

    last = await db.scalar(
        select(Message.text)
        .where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
        .order_by(Message.id.desc())
        .limit(1)
    )
    return bool(last and ASKS_INSCRIPTION_RE.search(last))
