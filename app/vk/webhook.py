"""Обработка событий VK Callback API (message_new / message_reply).

Валидация и ответ «ok» происходят в роутере (app/api/vk.py) за < 5 сек;
сама обработка уходит в фоновую задачу с собственной сессией БД — ВК ретраит
недоставленные события, дедупликация по external_message_id это покрывает.
"""
import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import pick_ai_provider
from app.db.models import (
    AIRun, Client, Dialog, DialogPingState, DialogStatusConfig, DialogType,
    Message, MessageRole, VkGroup,
)
from app.logging_context import current_dialog_type
from app.utils.time import msk_now

logger = logging.getLogger(__name__)

INITIAL_STATUS_NAME = "Поинтересовался"


@dataclass
class VkIncomingMessage:
    vk_user_id: int
    peer_id: int
    text: str
    external_message_id: str | None
    random_id: int
    files: list[str] = field(default_factory=list)
    audio_urls: list[str] = field(default_factory=list)
    admin_author_id: int | None = None


def _largest_photo_url(photo: dict) -> str | None:
    sizes = photo.get("sizes") or []
    if not sizes:
        return photo.get("orig_photo", {}).get("url")
    best = max(sizes, key=lambda s: (s.get("width", 0) or 0) * (s.get("height", 0) or 0))
    return best.get("url")


def parse_message_event(payload: dict) -> VkIncomingMessage | None:
    """Нормализует объект события message_new/message_reply.

    Возвращает None, если в сообщении нет ни текста, ни распознанных вложений.
    """
    obj = payload.get("object") or {}
    # Callback API ≥5.103: object = {message, client_info}; раньше object был самим сообщением.
    msg = obj.get("message") or obj
    from_id = msg.get("from_id")
    peer_id = msg.get("peer_id") or from_id
    if from_id is None:
        return None

    text = (msg.get("text") or "").strip()
    files: list[str] = []
    audio_urls: list[str] = []
    placeholders: list[str] = []
    for att in msg.get("attachments") or []:
        att_type = att.get("type")
        if att_type == "photo":
            url = _largest_photo_url(att.get("photo") or {})
            if url:
                files.append(url)
        elif att_type == "audio_message":
            am = att.get("audio_message") or {}
            url = am.get("link_mp3") or am.get("link_ogg")
            if url:
                audio_urls.append(url)
            placeholders.append("[голосовое сообщение]")
        elif att_type == "sticker":
            placeholders.append("[Стикер]")
        elif att_type == "video":
            placeholders.append("[видео]")

    if not text:
        if audio_urls or "[голосовое сообщение]" in placeholders:
            text = "[голосовое сообщение]"
        elif placeholders:
            text = placeholders[0]
        elif files:
            text = "[фото]"
        else:
            return None  # нечего обрабатывать (пересланное без текста и т.п.)

    message_id = msg.get("id") or msg.get("conversation_message_id")
    return VkIncomingMessage(
        vk_user_id=int(from_id),
        peer_id=int(peer_id),
        text=text,
        external_message_id=str(message_id) if message_id else None,
        random_id=int(msg.get("random_id") or 0),
        files=files,
        audio_urls=audio_urls,
        admin_author_id=msg.get("admin_author_id"),
    )


async def _resolve_dialog_type(db: AsyncSession, group: VkGroup) -> tuple[int | None, str]:
    """Тип диалога группы, либо первый активный DialogType как дефолт."""
    if group.dialog_type_id:
        dt = await db.get(DialogType, group.dialog_type_id)
        if dt and dt.is_active:
            return dt.id, dt.name
    result = await db.execute(
        select(DialogType).where(DialogType.is_active == True).order_by(DialogType.id)
    )
    default_type = result.scalars().first()
    if default_type:
        return default_type.id, default_type.name
    return None, "default"


async def _get_or_create_client(db: AsyncSession, group: VkGroup, vk_user_id: int) -> Client:
    client = await db.scalar(
        select(Client).where(
            Client.vk_group_id == group.id,
            Client.vk_user_id == vk_user_id,
        )
    )
    if not client:
        client = Client(vk_user_id=vk_user_id, vk_group_id=group.id, source=f"vk:{group.group_id}")
        db.add(client)
        await db.flush()
    return client


async def _get_or_create_dialog(
    db: AsyncSession, client: Client, type_id: int | None
) -> Dialog:
    dialog = await db.scalar(
        select(Dialog).where(Dialog.client_id == client.id, Dialog.type_id == type_id)
    )
    if dialog:
        return dialog
    initial_status = await db.scalar(
        select(DialogStatusConfig).where(
            DialogStatusConfig.name == INITIAL_STATUS_NAME,
            DialogStatusConfig.is_active == True,
        )
    )
    dialog = Dialog(
        client_id=client.id,
        type_id=type_id,
        current_status_id=initial_status.id if initial_status else None,
        is_test=False,
        ai_provider=pick_ai_provider(client.id),
    )
    db.add(dialog)
    await db.flush()
    return dialog


async def handle_message_new(db: AsyncSession, group: VkGroup, msg: VkIncomingMessage) -> None:
    """Входящее сообщение пользователя: сохранить, запустить ИИ, отправить ответ."""
    client = await _get_or_create_client(db, group, msg.vk_user_id)
    type_id, type_name = await _resolve_dialog_type(db, group)
    current_dialog_type.set(type_name)
    dialog = await _get_or_create_dialog(db, client, type_id)
    ctx = f"vk={group.group_id}/{msg.vk_user_id}"

    # Дедуп: ВК ретраит события. Сообщение с завершённым AIRun — пропускаем;
    # сообщение без ответа (воркер убит посреди run_ai) — переобрабатываем.
    client_message: Message | None = None
    if msg.external_message_id:
        existing = await db.scalar(
            select(Message).where(
                Message.dialog_id == dialog.id,
                Message.external_message_id == msg.external_message_id,
            )
        )
        if existing is not None:
            run_exists = await db.scalar(
                select(AIRun.id).where(AIRun.input_message_id == existing.id).limit(1)
            )
            if run_exists is not None:
                await db.commit()
                logger.info("[%s] vk duplicate skipped | external_message_id=%s", ctx, msg.external_message_id)
                return
            logger.info(
                "[%s] vk reprocessing message without reply | external_message_id=%s | msg_id=%s",
                ctx, msg.external_message_id, existing.id,
            )
            client_message = existing

    if client_message is None:
        msg_metadata: dict | None = None
        if msg.files or msg.audio_urls:
            msg_metadata = {}
            if msg.files:
                msg_metadata["files"] = msg.files
            if msg.audio_urls:
                msg_metadata["audio_urls"] = msg.audio_urls
        client_message = Message(
            dialog_id=dialog.id,
            role=MessageRole.client,
            text=msg.text,
            external_message_id=msg.external_message_id,
            msg_metadata=msg_metadata,
        )
        db.add(client_message)
        dialog.last_message_at = msk_now()
        try:
            await db.flush()
        except IntegrityError:
            # Гонка: конкурентная доставка того же события уже вставила сообщение
            # и владеет ответом — выходим, чтобы не сделать второй AI-ран.
            await db.rollback()
            logger.info("[%s] vk duplicate skipped (race) | external_message_id=%s", ctx, msg.external_message_id)
            return

    ping_state = await db.scalar(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
    )
    if ping_state:
        await db.delete(ping_state)
        logger.info("[%s] ping state reset — client responded", ctx)

    await db.commit()

    if dialog.ai_paused:
        logger.info("[%s] ai paused (operator took over) — message saved, no AI run", ctx)
        return

    from app.ai.runner import run_ai
    output, ai_run, image_urls, reply_text = await run_ai(db, dialog, client_message)

    if output.need_curator:
        logger.info("[%s] need_curator=True — reply held for review", ctx)
        return
    if not reply_text and not image_urls:
        logger.info("[%s] empty reply — nothing to send", ctx)
        return

    # Фото-вложения через VK upload API пока не поддержаны — URL уходят текстом,
    # ВК сам рендерит превью ссылок.
    outgoing_text = reply_text or ""
    if image_urls:
        outgoing_text = (outgoing_text + "\n" + "\n".join(image_urls)).strip()

    from app.vk.sender import VkApiError, VkMessagesForbiddenError, send_to_dialog
    try:
        vk_message_id = await send_to_dialog(db, dialog, outgoing_text)
    except VkMessagesForbiddenError:
        await db.commit()  # vk_blocked проставлен в send_to_dialog
        return
    except (VkApiError, Exception):
        logger.exception("[%s] vk reply send failed", ctx)
        return

    # Проставляем VK id на исходящее сообщение: message_reply о нашей же отправке
    # придёт в вебхук, и по этому id (и random_id≠0) мы его отличим от оператора.
    if ai_run.output_message_id and vk_message_id:
        ai_message = await db.get(Message, ai_run.output_message_id)
        if ai_message and not ai_message.external_message_id:
            ai_message.external_message_id = str(vk_message_id)
    dialog.last_message_at = msk_now()
    await db.commit()
    logger.info("[%s] vk reply sent | vk_message_id=%s", ctx, vk_message_id)


async def handle_message_reply(db: AsyncSession, group: VkGroup, msg: VkIncomingMessage) -> None:
    """Исходящее сообщение сообщества. Наши API-отправки (random_id ≠ 0) пропускаем;
    сообщение живого оператора сохраняем как curator и ставим ИИ на паузу."""
    if msg.random_id:
        return  # наша же отправка через messages.send — эхо не обрабатываем

    client = await _get_or_create_client(db, group, msg.peer_id)
    type_id, type_name = await _resolve_dialog_type(db, group)
    current_dialog_type.set(type_name)
    dialog = await _get_or_create_dialog(db, client, type_id)
    ctx = f"vk={group.group_id}/{msg.peer_id}"

    if msg.external_message_id:
        existing = await db.scalar(
            select(Message.id).where(
                Message.dialog_id == dialog.id,
                Message.external_message_id == msg.external_message_id,
            )
        )
        if existing is not None:
            await db.commit()
            return

    message = Message(
        dialog_id=dialog.id,
        role=MessageRole.curator,
        text=msg.text,
        external_message_id=msg.external_message_id,
        msg_metadata={"vk_operator": True, "admin_author_id": msg.admin_author_id}
        if msg.admin_author_id else {"vk_operator": True},
    )
    db.add(message)
    dialog.last_message_at = msk_now()
    if not dialog.ai_paused:
        dialog.ai_paused = True
        logger.info("[%s] operator replied from VK — AI paused", ctx)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()


async def process_event(group_pk: int, payload: dict) -> None:
    """Фоновая обработка события в собственной сессии БД."""
    from app.db.session import AsyncSessionLocal

    event_type = payload.get("type")
    msg = parse_message_event(payload)
    if msg is None:
        logger.info("vk event %s skipped — no processable content", event_type)
        return
    try:
        async with AsyncSessionLocal() as db:
            group = await db.get(VkGroup, group_pk)
            if not group:
                return
            if event_type == "message_new":
                await handle_message_new(db, group, msg)
            elif event_type == "message_reply":
                await handle_message_reply(db, group, msg)
    except Exception:
        logger.exception("vk event %s processing failed | group_pk=%s", event_type, group_pk)


# asyncio.create_task() держит только слабую ссылку на таску в event loop — без
# сильной ссылки где-то ещё таска может быть собрана GC ДО завершения, вместе с
# необработанным исключением (даже до его except-блока). Сет ниже держит ссылку,
# пока таска не завершится, чтобы process_event().except всегда успевал отработать.
_background_tasks: set[asyncio.Task] = set()


def schedule_event(group_pk: int, payload: dict) -> None:
    """Запуск обработки события в фоне (роутер должен ответить «ok» мгновенно)."""
    task = asyncio.create_task(process_event(group_pk, payload))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
