"""Отправка клиенту, не зависящая от того, в каком мессенджере он пишет.

Отправляют в диалог из четырёх мест: ответ ИИ (app.vk.webhook), пинги
(app.ping.worker), молчаливое приветствие (app.ping.silent_greeting) и ответ
менеджера из панели (app.api.chat). Все они знают только диалог и текст, а
куда именно уходит сообщение — в сообщество ВК или боту MAX — решается здесь,
по платформе канала, к которому привязан клиент.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Dialog, VkGroup

logger = logging.getLogger(__name__)


class MessagesForbiddenError(RuntimeError):
    """Писать клиенту нельзя, и это не временная ошибка.

    ВК: клиент запретил сообщения сообщества (900/901/902). MAX: остановил бота
    или удалил диалог. В обоих случаях диалог помечается `vk_blocked`, а
    отправку не ретраят.
    """


def platform_of(group: VkGroup | None) -> str:
    """Платформа канала: 'vk' или 'max'.

    Значение колонки проставляется при вставке в базу, поэтому у ещё не
    сохранённого объекта его может не быть — по умолчанию считаем ВК: с него
    система начиналась, и все старые записи именно такие.
    """
    return getattr(group, "platform", None) or "vk"


async def channel_of(db: AsyncSession, dialog: Dialog) -> VkGroup | None:
    """Канал (сообщество ВК или бот MAX), через который идёт диалог."""
    client = await db.get(Client, dialog.client_id)
    if not client or not client.vk_group_id:
        return None
    return await db.get(VkGroup, client.vk_group_id)


async def send_to_dialog(db: AsyncSession, dialog: Dialog, text: str):
    """Отправить текст клиенту диалога через его мессенджер.

    Возвращает объект отправки с `message_id` и `random_ids` (см.
    app.vk.sender.SentMessage и app.max.client.MaxSentMessage) — их читает
    app.vk.outgoing.mark_delivered.
    """
    group = await channel_of(db, dialog)
    if platform_of(group) == "max":
        from app.max.sender import send_to_dialog as send_max

        return await send_max(db, dialog, text)

    from app.vk.sender import send_to_dialog as send_vk

    return await send_vk(db, dialog, text)
