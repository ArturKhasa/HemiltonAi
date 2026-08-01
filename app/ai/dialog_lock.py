"""Один прогон ИИ на диалог за раз, и ответ — только на последнюю реплику.

Клиент часто пишет двумя сообщениями подряд: «я буду жаловаться!» в 04:06 и
ровно то же в 04:07 (диалог 74). Прогон занимает 10-60 секунд, поэтому второе
сообщение приходило, пока первое ещё обрабатывалось: два независимых прогона
читали одно и то же состояние диалога и отвечали каждый своё. Клиент получал две
простыни подряд, ни одна из которых не видела другую.

Тем же путём обходилась и пауза куратора: флаг ставится в конце прогона, а
второй прогон стартовал раньше и проверку `ai_paused` уже прошёл.

Живой менеджер в такой ситуации дочитывает обе реплики и отвечает один раз —
здесь так же: прогон, у которого за спиной появилось более свежее сообщение
клиента, молча уступает место следующему. Тот увидит в истории обе реплики.

uvicorn запущен с --workers 1, поэтому обычной asyncio-блокировки достаточно.
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageRole

logger = logging.getLogger(__name__)

_locks: dict[int, asyncio.Lock] = {}
# Выше этого числа подчищаем свободные блокировки: диалоги копятся месяцами, а
# нужны только те, что обрабатываются прямо сейчас.
_PRUNE_THRESHOLD = 512


def dialog_lock(dialog_id: int) -> asyncio.Lock:
    """Блокировка этого диалога. Одна и та же для всех вызовов."""
    lock = _locks.get(dialog_id)
    if lock is None:
        if len(_locks) >= _PRUNE_THRESHOLD:
            for stale_id in [i for i, l in _locks.items() if not l.locked()]:
                del _locks[stale_id]
        lock = _locks.setdefault(dialog_id, asyncio.Lock())
    return lock


async def superseded_by_newer_message(
    db: AsyncSession, dialog_id: int, message_id: int,
) -> bool:
    """За время ожидания клиент прислал ещё сообщение — отвечать будет следующий
    прогон, он увидит в истории и эту реплику, и ту."""
    found = await db.scalar(
        select(Message.id)
        .where(
            Message.dialog_id == dialog_id,
            Message.role == MessageRole.client,
            Message.id > message_id,
        )
        .limit(1)
    )
    if found is not None:
        logger.info(
            "dialog=%s: реплика %s устарела — отвечаем на %s", dialog_id, message_id, found,
        )
    return found is not None
