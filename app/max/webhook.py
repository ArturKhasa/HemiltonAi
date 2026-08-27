"""Обработка событий MAX Bot API (`Update`).

Событие разбирается в тот же `VkIncomingMessage`, что и событие ВК, и дальше
идёт общей дорогой (app.vk.webhook.handle_message_new): дедуп, блокировка
диалога, пауза «клиент дописывает», прогон модели, отправка. Логика продаж не
должна знать, из какого мессенджера пришло сообщение.

Чего у MAX нет по сравнению с ВК:

- эха исходящих. ``message_reply`` в MAX нет вовсе, а ``message_created``
  приходит только о ВХОДЯЩИХ: о сообщении, отправленном от имени бота, MAX не
  рассказывает никому. А отправляет их не только эта панель — к боту подключён
  Wazzup, из которого пишут менеджеры ОП. Ловит такие реплики отдельный
  наблюдатель, читающий историю диалога сам (app.max.manager_watch);
  ``handle_bot_message`` ниже остаётся на случай, если MAX всё же начнёт эти
  события присылать;
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

from app.db.models import Client, Dialog, Message, MessageRole, VkGroup
from app.vk.webhook import VkIncomingMessage

logger = logging.getLogger(__name__)


# «/start», «/start sweetgold», «/start@bot» — команда запуска. Всё, что после
# неё, MAX передаёт из диплинка: это метка рекламной кампании.
_START_COMMAND_RE = re.compile(r"^/start(?:@\S+)?(?:\s+(?P<payload>.+))?$", re.IGNORECASE)


def _message(payload: dict) -> dict:
    return payload.get("message") or {}


def _message_mid(message: dict) -> str | None:
    mid = ((message.get("body") or {}).get("mid"))
    return str(mid) if mid is not None else None


def _is_our_bot_message(bot: VkGroup, payload: dict) -> bool:
    """Сообщение отправлено именно нашим ботом, а не другим ботом из чата."""
    sender = _message(payload).get("sender") or {}
    sender_id = sender.get("user_id")
    return bool(
        sender.get("is_bot") and sender_id is not None
        and int(sender_id) == int(bot.group_id)
    )


def _recipient_user_id(message: dict) -> int | None:
    """Кому бот написал в личном диалоге; у группового чата пользователя нет."""
    recipient = message.get("recipient") or {}
    user_id = recipient.get("user_id")
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _is_group_message(payload: dict) -> bool:
    """Групповые чаты не являются личным диалогом продажи.

    В них пишет не только клиент: участником может быть менеджер. Пока у нас
    нет привязки одной карточки к участникам группового чата, безопаснее не
    запускать AI по сообщениям из него, чем принять менеджера за клиента.
    """
    chat_type = ((_message(payload).get("recipient") or {}).get("chat_type") or "").lower()
    return chat_type in {"chat", "channel"}


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


async def _dialog_for_client_message(
    db: AsyncSession, bot: VkGroup, message: VkIncomingMessage,
) -> Dialog:
    """Найти или завести карточку клиента, не запуская AI.

    Этой дорогой идут только защитные проверки MAX. Обычный входящий текст по-
    прежнему обрабатывает общий `handle_message_new`.
    """
    from app.sales.ref_tags import RefTagService
    from app.vk.webhook import _get_or_create_client, _get_or_create_dialog, _resolve_dialog_type

    client = await _get_or_create_client(
        db, bot, message.vk_user_id, ref=message.ref,
        first_name=message.first_name, last_name=message.last_name,
    )
    type_id, _ = await _resolve_dialog_type(db, bot)
    tag = (client.marketing_tags or [None])[0]
    ai_allowed = await RefTagService(db).ai_allowed(tag, type_id)
    return await _get_or_create_dialog(db, client, type_id, ai_allowed=ai_allowed)


async def _pause_for_manager_message(
    db: AsyncSession, bot: VkGroup, message: VkIncomingMessage, reason: str,
) -> Dialog:
    """Передать карточку человеку и остановить её пинги."""
    from app.ping.worker import stop_pings

    dialog = await _dialog_for_client_message(db, bot, message)
    if not dialog.ai_paused:
        dialog.ai_paused = True
        logger.info("[max=%s/%s] %s — ИИ на паузе", bot.group_id, message.vk_user_id, reason)
    await stop_pings(db, dialog.id, reason)
    return dialog


async def pause_if_first_message_has_manager_reply(
    db: AsyncSession, bot: VkGroup, payload: dict, message: VkIncomingMessage,
) -> bool:
    """Не включать AI, если до первого текста клиента менеджер уже ответил.

    В обычном личном диалоге MAX исходящие менеджера приходят вебхуком и ловятся
    `handle_bot_message` ниже. Историю читаем как запасной путь на случай, если
    сотрудник отвечал через другой интерфейс и событие успело прийти раньше
    подключения нашей системы. MAX отдаёт сообщения последними первыми.
    """
    from app.max.client import MaxApiError, get_messages

    # Проверка нужна ровно при первом появлении клиента у нас. Дальше исходящие
    # менеджера ловятся отдельным событием, а повторный запрос истории только
    # замедлял бы каждый ход.
    client = await db.scalar(
        select(Client).where(
            Client.vk_group_id == bot.id, Client.vk_user_id == message.vk_user_id,
        )
    )
    if client:
        known = await db.scalar(select(Dialog.id).where(Dialog.client_id == client.id).limit(1))
        if known is not None:
            return False

    chat_id = ((_message(payload).get("recipient") or {}).get("chat_id"))
    if chat_id is None:
        return False
    try:
        history = await get_messages(bot.access_token, int(chat_id))
    except (MaxApiError, TypeError, ValueError) as exc:
        # У личных диалогов некоторые версии API историю не возвращают. Это не
        # повод молча отключать AI для всех новых лидов: исходящее событие бота
        # всё равно обработается отдельно.
        logger.info("[max=%s/%s] историю до первого сообщения не прочитать: %s", bot.group_id, message.vk_user_id, exc)
        return False
    except Exception as exc:
        logger.warning("[max=%s/%s] проверка истории MAX не удалась: %s", bot.group_id, message.vk_user_id, exc)
        return False

    current_mid = message.external_message_id
    for historic in history:
        historic_mid = _message_mid(historic)
        if current_mid and historic_mid == current_mid:
            continue
        sender = historic.get("sender") or {}
        if not sender.get("is_bot") or int(sender.get("user_id") or 0) != int(bot.group_id):
            continue
        # Наше же сообщение уже есть в БД с идентификатором MAX. Любая другая
        # исходящая реплика бота означает, что диалог ведёт менеджер или другая
        # операторская система, а не AI этого сервиса.
        if historic_mid:
            tracked = await db.scalar(
                select(Message.id).where(Message.external_message_id == historic_mid).limit(1)
            )
            if tracked is not None:
                continue
        await _pause_for_manager_message(db, bot, message, "до первого сообщения уже ответил менеджер в MAX")
        await db.commit()
        return True
    return False


async def handle_bot_message(db: AsyncSession, bot: VkGroup, payload: dict) -> bool:
    """Исходящее MAX-сообщение бота: своё пропускаем, менеджерское ставит на паузу.

    На боевом трафике этот путь не срабатывает ни разу: MAX не присылает
    событий о сообщениях, отправленных от имени бота, чьей бы рукой они ни были
    отправлены (за трое суток — ни одной записи с ролью curator при десятках
    таких реплик в истории самого MAX). Ответы менеджера мимо панели ловит
    app.max.manager_watch, читая историю диалога. Обработчик оставлен как есть:
    начнёт MAX присылать эти события — перехват увидим на секунду раньше.
    """
    if not _is_our_bot_message(bot, payload) or _is_group_message(payload):
        return False
    raw = _message(payload)
    recipient_id = _recipient_user_id(raw)
    if recipient_id is None:
        return False
    outgoing_mid = _message_mid(raw)

    # Сначала выясняем, не наше ли это отправленное сообщение. Проверяем по ID,
    # а при короткой гонке вебхука — по ещё не отмеченному тексту.
    if outgoing_mid:
        own = await db.scalar(
            select(Message.id).where(
                Message.external_message_id == outgoing_mid,
                Message.role != MessageRole.client,
            ).limit(1)
        )
        if own is not None:
            await db.commit()
            return True

    body = raw.get("body") or {}
    outgoing_text = (body.get("text") or "").strip() or "[вложение]"
    probe = VkIncomingMessage(
        vk_user_id=recipient_id,
        peer_id=recipient_id,
        text=outgoing_text,
        external_message_id=outgoing_mid,
        random_id=0,
    )
    dialog = await _dialog_for_client_message(db, bot, probe)
    pending_own = await db.scalar(
        select(Message.id).where(
            Message.dialog_id == dialog.id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
            Message.external_message_id.is_(None),
            Message.text == outgoing_text,
        ).order_by(Message.id.desc()).limit(1)
    )
    if pending_own is not None:
        await db.commit()
        return True

    if outgoing_mid:
        duplicate = await db.scalar(
            select(Message.id).where(
                Message.dialog_id == dialog.id,
                Message.external_message_id == outgoing_mid,
            ).limit(1)
        )
        if duplicate is not None:
            await db.commit()
            return True

    db.add(Message(
        dialog_id=dialog.id,
        role=MessageRole.curator,
        text=outgoing_text,
        external_message_id=outgoing_mid,
        msg_metadata={"max_operator": True},
    ))
    await _pause_for_manager_message(db, bot, probe, "менеджер ответил в MAX")
    await db.commit()
    return True


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
    # Клиент снова нажал «Начать» — писать ему точно можно, что бы ни отвечал
    # MAX в прошлый раз.
    if dialog.vk_blocked:
        dialog.vk_blocked = False
        logger.info("[%s] клиент вернулся — отметка «отправка запрещена» снята", ctx)
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
    """Пользователь остановил бота: пинги гасим, отправку заранее не запрещаем.

    Отметку `vk_blocked` ставит только фактический отказ MAX на отправку (см.
    app.max.sender.send_to_dialog) — как это всегда работало в ВК. Раньше её
    ставило само событие, и 27.08 в панели «в блоке» оказались 162 MAX-диалога
    из 361. Проверка по истории MAX: в 17 из 60 таких диалогов ПОСЛЕ отметки
    боту приходили новые исходящие (до шестнадцати штук) — то есть писать этим
    клиентам можно было всё это время, а мы молчали навсегда: снять отметку
    было нечем (ОП, 27.08: «через панель отображается что клиент заблокировал в
    вк, пошла проверять через ваззап, все ок, мы не в блоке у клиента»).

    Настоящий стоп-бот виден и без события: первая же отправка вернёт отказ, и
    диалог пометится ровно тогда, когда это правда. Пинги при этом гасим сразу
    — гонять воронку туда, где бот остановлен, незачем.
    """
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
        await stop_pings(db, dialog.id, "пользователь остановил бота в MAX")
    await db.commit()
    logger.info(
        "[max=%s/%s] бот остановлен пользователем — пинги погашены",
        bot.group_id, user_id,
    )


async def handle_dialog_removed(db: AsyncSession, bot: VkGroup, payload: dict) -> None:
    """Пользователь удалил переписку с ботом. Это не запрет писать.

    Удалённый диалог в MAX возвращается от первого же сообщения бота — в
    боевой истории такие переписки продолжались и после удаления. Поэтому
    здесь только запись в лог: и пинги, и ход ИИ работают дальше, а если
    отправка всё же окажется запрещена, её отказ пометит диалог сам.
    """
    user_id = payload.get("user_id") or (payload.get("user") or {}).get("user_id")
    logger.info("[max=%s/%s] клиент удалил переписку — продолжаем как обычно", bot.group_id, user_id)


async def _remember_dialog_chat(db: AsyncSession, bot: VkGroup, payload: dict) -> None:
    """Запомнить chat_id личного диалога — без него не прочитать его историю.

    В событии он приходит сам собой, а получить его иначе нельзя: истории по
    `user_id` MAX не отдаёт, а список чатов бота для личных диалогов пуст.
    Диалог, где клиент только нажал «Начать», без этого остался бы вне
    наблюдения за ответами менеджера (app.max.manager_watch) — а это ровно тот
    случай, с которого ОП и начал: карточка есть, переписку ведёт менеджер, у
    нас по ней ни одного сообщения.
    """
    from app.max.manager_watch import remember_chat_id

    raw = _message(payload)
    recipient = raw.get("recipient") or {}
    if _is_group_message(payload):
        return
    user_id = (
        recipient.get("user_id") if _is_our_bot_message(bot, payload)
        else (raw.get("sender") or {}).get("user_id")
    )
    if user_id is None:
        return
    try:
        await remember_chat_id(db, bot, int(user_id), recipient.get("chat_id"))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("[max=%s/%s] chat_id не сохранён: %s", bot.group_id, user_id, exc)


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
                if _is_group_message(payload):
                    # Групповой чат может содержать менеджера и клиента. У
                    # карточки пока нет модели его участников, так что любые
                    # ответы AI здесь небезопасны.
                    logger.info("max group message skipped — AI only works in personal dialogs")
                    return
                if await handle_bot_message(db, bot, payload):
                    await _remember_dialog_chat(db, bot, payload)
                    return
                # «/start» — не сообщение клиента, а нажатая кнопка «Начать».
                start = start_command(payload)
                if start:
                    await handle_start(db, bot, **start)
                    await _remember_dialog_chat(db, bot, payload)
                    return
                msg = parse_message_created(payload)
                if msg is None:
                    logger.info("max event message_created пропущено — нечего обрабатывать")
                    return
                await pause_if_first_message_has_manager_reply(db, bot, payload, msg)
                await handle_message_new(db, bot, msg)
                # После хода, а не до: карточку клиента заводит он же.
                await _remember_dialog_chat(db, bot, payload)
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
            elif update_type == "bot_stopped":
                await handle_bot_stopped(db, bot, payload)
            elif update_type == "dialog_removed":
                await handle_dialog_removed(db, bot, payload)
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
