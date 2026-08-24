"""Обработка событий MAX Bot API (`Update`).

Событие разбирается в тот же `VkIncomingMessage`, что и событие ВК, и дальше
идёт общей дорогой (app.vk.webhook.handle_message_new): дедуп, блокировка
диалога, пауза «клиент дописывает», прогон модели, отправка. Логика продаж не
должна знать, из какого мессенджера пришло сообщение.

Чего у MAX нет по сравнению с ВК:

- эха собственных отправок. В диалог бота с пользователем больше никто писать
  не может, поэтому `message_reply` и распознавание своего `random_id` здесь
  не нужны;
- переписки, которая шла до подключения: у бота её не бывает.

Чего нет у ВК: старта диалога как отдельного события. В MAX человек нажимает
«Начать» — и ждёт, что бот заговорит первым. Приходит это двумя путями, и оба
ведут в handle_start: событием `bot_started` и/или сообщением «/start» (за
командой следует payload диплинка — прямой аналог `ref` рекламной ссылки ВК).
Что именно пришлёт MAX, зависит от того, как пользователь открыл бота, поэтому
handle_start сделан идемпотентным: поздороваться он даст ровно один раз.
"""
import asyncio
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Dialog, VkGroup
from app.vk.webhook import VkIncomingMessage

logger = logging.getLogger(__name__)


# «/start», «/start sweetgold», «/start@bot» — команда запуска. Всё, что после
# неё, MAX передаёт из диплинка: это метка рекламной кампании.
_START_COMMAND_RE = re.compile(r"^/start(?:@\S+)?(?:\s+(?P<payload>.+))?$", re.IGNORECASE)


def start_command(payload: dict) -> dict | None:
    """Событие `message_created`, которое на самом деле означает «нажал Начать».

    Возвращает данные пользователя и метку диплинка, либо None — если это
    обычное сообщение. Команду в историю диалога не кладём: клиент её не писал,
    а модель, увидев в переписке «/start», начинает объяснять, что это такое.
    """
    message = payload.get("message") or {}
    sender = message.get("sender") or {}
    body = message.get("body") or {}
    if sender.get("user_id") is None or sender.get("is_bot"):
        return None
    match = _START_COMMAND_RE.match((body.get("text") or "").strip())
    if not match:
        return None
    return {
        "user_id": int(sender["user_id"]),
        "ref": (match.group("payload") or "").strip() or None,
        "first_name": (sender.get("first_name") or "").strip() or None,
        "last_name": (sender.get("last_name") or "").strip() or None,
    }


def parse_message_created(payload: dict) -> VkIncomingMessage | None:
    """Нормализует событие `message_created`.

    Возвращает None, если разбирать нечего: сообщение от бота (своё эхо в
    групповых чатах), без отправителя или без текста и распознанных вложений.
    """
    message = payload.get("message") or {}
    sender = message.get("sender") or {}
    body = message.get("body") or {}

    user_id = sender.get("user_id")
    if user_id is None or sender.get("is_bot"):
        return None

    text = (body.get("text") or "").strip()
    files: list[str] = []
    audio_urls: list[str] = []
    sticker_files: list[str] = []
    placeholders: list[str] = []
    transcription: str | None = None

    for att in body.get("attachments") or []:
        att_type = att.get("type")
        url = ((att.get("payload") or {}).get("url")) or None
        if att_type == "image":
            if url:
                files.append(url)
        elif att_type == "audio":
            if url:
                audio_urls.append(url)
            # MAX расшифровывает голосовые сам. Своя расшифровка (Whisper в
            # app.ai.audio) остаётся запасным путём: она стоит денег и времени.
            transcription = (att.get("transcription") or "").strip() or transcription
            placeholders.append("[голосовое сообщение]")
        elif att_type == "sticker":
            placeholders.append("[Стикер]")
            if url:
                sticker_files.append(url)
        elif att_type == "video":
            placeholders.append("[видео]")
        elif att_type == "file":
            if url:
                files.append(url)  # чек или макет — попадёт куратору в карточку
            filename = att.get("filename")
            placeholders.append(f"[файл: {filename}]" if filename else "[файл]")
        elif att_type == "share":
            placeholders.append("[ссылка]")
        elif att_type == "location":
            placeholders.append("[геопозиция]")
        elif att_type == "contact":
            placeholders.append("[контакт]")

    if not text:
        if transcription:
            text = transcription
        elif audio_urls or "[голосовое сообщение]" in placeholders:
            text = "[голосовое сообщение]"
        elif placeholders:
            text = placeholders[0]
        elif files:
            text = "[фото]"
        else:
            return None
    elif placeholders:
        text = text + "\n" + " ".join(placeholders)

    mid = body.get("mid")
    return VkIncomingMessage(
        vk_user_id=int(user_id),
        peer_id=int(user_id),
        text=text,
        external_message_id=str(mid) if mid else None,
        random_id=0,
        files=files,
        audio_urls=[] if transcription else audio_urls,
        sticker_files=sticker_files,
        first_name=(sender.get("first_name") or "").strip() or None,
        last_name=(sender.get("last_name") or "").strip() or None,
    )


async def handle_start(
    db: AsyncSession, bot: VkGroup, user_id: int, ref: str | None = None,
    first_name: str | None = None, last_name: str | None = None,
) -> None:
    """Пользователь начал диалог с ботом: завести клиента и поздороваться.

    Приветствие берётся из того же приветственного скрипта, что и в ВК, — там
    оно уходит в ответ на первое сообщение клиента, здесь в ответ на «Начать».
    Здороваемся один раз: если в диалоге уже есть наше сообщение, выходим.
    В ВК аналога нет — сообществу приветствие по кнопке шлёт сам ВК.
    """
    from app.ai.dialog_lock import dialog_lock
    from app.ai.runner import run_greeting
    from app.logging_context import current_dialog_type
    from app.sales.ref_tags import RefTagService
    from app.vk.webhook import (
        _get_or_create_client, _get_or_create_dialog, _resolve_dialog_type, deliver_parts,
    )

    ctx = f"max={bot.group_id}/{user_id}"
    client = await _get_or_create_client(
        db, bot, user_id, ref=ref, first_name=first_name, last_name=last_name,
    )
    type_id, type_name = await _resolve_dialog_type(db, bot)
    current_dialog_type.set(type_name)

    client_tag = (client.marketing_tags or [None])[0]
    ai_allowed = await RefTagService(db).ai_allowed(client_tag, type_id)
    dialog = await _get_or_create_dialog(db, client, type_id, ai_allowed=ai_allowed)
    await db.commit()
    logger.info("[%s] пользователь начал диалог с ботом | payload=%r", ctx, ref)

    # Один ход на диалог за раз: «Начать» и первое сообщение клиента приходят
    # секунда в секунду, и без блокировки он получил бы два приветствия.
    async with dialog_lock(dialog.id):
        await db.refresh(dialog)
        if dialog.ai_paused:
            logger.info("[%s] ИИ на паузе — приветствие не отправляем", ctx)
            return
        parts = await run_greeting(db, dialog, client, ctx)
        if not parts:
            # Приветственного скрипта нет (или мы уже здоровались) — работаем
            # как в ВК: первым напишет клиент, ответ соберёт обычный ход.
            return
        await deliver_parts(db, bot, dialog, parts, ctx)


async def handle_bot_stopped(db: AsyncSession, bot: VkGroup, payload: dict) -> None:
    """Пользователь остановил бота или удалил диалог — писать ему больше нельзя."""
    from app.ping.worker import stop_pings

    user_id = payload.get("user_id") or (payload.get("user") or {}).get("user_id")
    if user_id is None:
        return
    client = await db.scalar(
        select(Client).where(
            Client.vk_group_id == bot.id, Client.vk_user_id == int(user_id),
        )
    )
    if not client:
        return
    dialogs = (
        await db.execute(select(Dialog).where(Dialog.client_id == client.id))
    ).scalars().all()
    for dialog in dialogs:
        dialog.vk_blocked = True
        await stop_pings(db, dialog.id, "пользователь остановил бота в MAX")
    await db.commit()
    logger.info(
        "[max=%s/%s] бот остановлен пользователем — диалоги помечены заблокированными",
        bot.group_id, user_id,
    )


async def process_event(bot_pk: int, payload: dict) -> None:
    """Фоновая обработка события в собственной сессии БД."""
    from app.db.session import AsyncSessionLocal
    from app.vk.webhook import handle_message_new

    update_type = payload.get("update_type")
    try:
        async with AsyncSessionLocal() as db:
            bot = await db.get(VkGroup, bot_pk)
            if not bot:
                return
            if update_type == "message_created":
                # «/start» — не сообщение клиента, а нажатая кнопка «Начать».
                start = start_command(payload)
                if start:
                    await handle_start(db, bot, **start)
                    return
                msg = parse_message_created(payload)
                if msg is None:
                    logger.info("max event message_created пропущено — нечего обрабатывать")
                    return
                await handle_message_new(db, bot, msg)
            elif update_type == "bot_started":
                user = payload.get("user") or {}
                if user.get("user_id") is None:
                    return
                await handle_start(
                    db, bot, int(user["user_id"]),
                    ref=(payload.get("payload") or "").strip() or None,
                    first_name=(user.get("first_name") or "").strip() or None,
                    last_name=(user.get("last_name") or "").strip() or None,
                )
            elif update_type in ("bot_stopped", "dialog_removed"):
                await handle_bot_stopped(db, bot, payload)
    except Exception:
        logger.exception("max event %s processing failed | bot_pk=%s", update_type, bot_pk)


# Как и в ВК-вебхуке: без сильной ссылки таску может собрать GC ещё до того,
# как отработает её except (см. app.vk.webhook._background_tasks).
_background_tasks: set[asyncio.Task] = set()


def schedule_event(bot_pk: int, payload: dict) -> None:
    """Запуск обработки в фоне — вебхук должен ответить мгновенно."""
    task = asyncio.create_task(process_event(bot_pk, payload))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
