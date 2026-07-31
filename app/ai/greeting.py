"""Приветствие отдаётся кодом, а не моделью.

Первое сообщение диалога — защищённый шаблон ОП: дословный текст, прикреплённые
фото и следом отдельным сообщением вопрос про имя/фамилию. Пока его формировала
модель, она этот шаблон переписывала: в диалоге 13 она получила скрипт #358 со
всеми токенами [photo-...], а отправила собственный пересказ без фото и без
строчки про любовь к родине, вклеив туда же вопрос из скрипта #362.

Правило воспроизводится на любой модели по-разному (gpt-4.1 копировал шаблон
точнее, gpt-5.6-luna вольнее), поэтому приветствие вынуто из-под модели совсем:
здесь нечего решать, есть готовый текст. Заодно экономится вызов модели на первом
сообщении каждого диалога.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools import _parse_tags
from app.db.models import Client, Dialog, Message, MessageRole, Script

logger = logging.getLogger(__name__)

# Метка приветственных скриптов в выгрузке ОП. Условие они заполняют вручную по
# своему регламенту, формулировка стабильна во всех разделах таблицы.
GREETING_CONDITION_MARKER = "первое приветственное"


async def dialog_has_outgoing(db: AsyncSession, dialog_id: int) -> bool:
    """Мы уже что-то писали в этот диалог (ИИ, пинг или живой куратор)."""
    found = await db.scalar(
        select(Message.id)
        .where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
        .limit(1)
    )
    return found is not None


async def pick_greeting_script(
    db: AsyncSession, type_id: int | None, client: Client | None,
) -> Script | None:
    """Приветствие под маркетинговый тег клиента.

    Тегированное всегда выигрывает у нетегированного — тег и заведён ради того,
    чтобы клиент с конкретной рекламы получил своё приветствие. Внутри одной
    группы берём наименьший id: в выгрузке лежит несколько одинаковых по условию
    приветствий без тега, и выбор должен быть воспроизводимым, а не случайным.
    """
    client_tags = set((client.marketing_tags if client else None) or [])

    # Явная привязка из админки сильнее подбора по тегу скрипта: там метка и тег
    # совпадают только пока их не разошлись руками, а метки правят постоянно.
    from app.sales.ref_tags import RefTagService
    svc = RefTagService(db)
    for tag in sorted(client_tags):
        row = await svc.get(tag, type_id)
        if row is not None and row.greeting_script_id:
            bound = await db.get(Script, row.greeting_script_id)
            if bound is not None and bound.is_active and (bound.phrase_text or "").strip():
                return bound
            logger.warning(
                "ref-метка %r ссылается на неактивный приветственный скрипт %s",
                tag, row.greeting_script_id,
            )

    q = select(Script).where(Script.is_active == True)
    if type_id is not None:
        q = q.where(Script.type_id == type_id)
    rows = (await db.execute(q.order_by(Script.id))).scalars().all()

    candidates = [
        s for s in rows
        if GREETING_CONDITION_MARKER in (s.condition or "").lower()
        and (s.phrase_text or "").strip()
    ]
    if not candidates:
        return None

    if client_tags:
        tagged = [
            s for s in candidates
            if _parse_tags(s.marketing_tag) and _parse_tags(s.marketing_tag) <= client_tags
        ]
        if tagged:
            return tagged[0]

    untagged = [s for s in candidates if not _parse_tags(s.marketing_tag)]
    return untagged[0] if untagged else None


async def resolve_greeting(
    db: AsyncSession, dialog: Dialog, client: Client | None, type_id: int | None,
) -> Script | None:
    """Скрипт приветствия, если этот ход — первое наше сообщение в диалоге.
    None — работаем как обычно, через модель."""
    if await dialog_has_outgoing(db, dialog.id):
        return None
    script = await pick_greeting_script(db, type_id, client)
    if script is None:
        logger.warning(
            "dialog=%s: приветственный скрипт не найден — приветствие отдаст модель",
            dialog.id,
        )
    return script
