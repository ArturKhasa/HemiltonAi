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

# Пауза между репликами одного хода (связка скриптов, см. ReplyPart).
FOLLOW_UP_DELAY_SECONDS = 2.0


@dataclass
class VkIncomingMessage:
    vk_user_id: int
    peer_id: int
    text: str
    external_message_id: str | None
    random_id: int
    files: list[str] = field(default_factory=list)
    audio_urls: list[str] = field(default_factory=list)
    # Картинки стикеров держим отдельно от files: там фото клиента, а стикер —
    # не фото. Модель их видит по-разному, см. runner._attachment_content.
    sticker_files: list[str] = field(default_factory=list)
    admin_author_id: int | None = None
    # Метка рекламной ссылки, по которой пришёл клиент (vk.me/club123?ref=sweetgold).
    # ВК присылает её только в ПЕРВОМ сообщении диалога.
    ref: str | None = None


# Размер превью стикера. Смысл («палец вверх», «сердечко», «грустный кот») виден
# и на мелком, а картинка едет в модель на каждом ходу вместе с историей —
# 128 px хватает и стоит дёшево. Анимированные ВК тоже отдаёт кадром PNG.
_STICKER_MIN_PX = 128


def _sticker_image_url(sticker: dict) -> str | None:
    """Превью стикера: самое мелкое из тех, что не меньше _STICKER_MIN_PX."""
    images = sticker.get("images") or sticker.get("images_with_background") or []
    sized = [i for i in images if i.get("url")]
    if not sized:
        return None
    big_enough = [i for i in sized if (i.get("width") or 0) >= _STICKER_MIN_PX]
    pick = min(big_enough or sized, key=lambda i: i.get("width") or 0) if big_enough else max(
        sized, key=lambda i: i.get("width") or 0
    )
    return pick.get("url")


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
    sticker_files: list[str] = []
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
            sticker_url = _sticker_image_url(att.get("sticker") or {})
            if sticker_url:
                sticker_files.append(sticker_url)
        elif att_type == "video":
            placeholders.append("[видео]")
        elif att_type == "doc":
            doc = att.get("doc") or {}
            url = doc.get("url")
            if url:
                files.append(url)  # чек/файл — попадёт в msg_metadata.files для куратора
            title = doc.get("title")
            placeholders.append(f"[файл: {title}]" if title else "[файл]")

    if not text:
        if audio_urls or "[голосовое сообщение]" in placeholders:
            text = "[голосовое сообщение]"
        elif placeholders:
            text = placeholders[0]
        elif files:
            text = "[фото]"
        else:
            return None  # нечего обрабатывать (пересланное без текста и т.п.)
    elif placeholders:
        # Пометка вложения рядом с текстом: раньше она бралась, только если
        # текста нет вовсе, и «спасибо 🙂» со стикером доходило до модели голым
        # текстом — вложения для неё не существовало. Стикер при этом не фото:
        # картинку его мы не сохраняем и в модель не отдаём, только пометку.
        text = text + "\n" + " ".join(placeholders)

    # У ссылки вида ?ref=adb_r&ref_source=rusover449 метка кампании — во ВТОРОМ
    # параметре, а в ref лежит тип площадки, общий для всей рекламы. Приоритет
    # ref_source, ref — запасной. На старых версиях Callback API объект события
    # и был сообщением, поэтому смотрим оба уровня.
    ref = (
        msg.get("ref_source") or obj.get("ref_source")
        or msg.get("ref") or obj.get("ref")
    )
    ref = str(ref).strip() if ref else None

    message_id = msg.get("id") or msg.get("conversation_message_id")
    return VkIncomingMessage(
        ref=ref or None,
        vk_user_id=int(from_id),
        peer_id=int(peer_id),
        text=text,
        external_message_id=str(message_id) if message_id else None,
        random_id=int(msg.get("random_id") or 0),
        files=files,
        audio_urls=audio_urls,
        sticker_files=sticker_files,
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


async def _get_or_create_client(
    db: AsyncSession, group: VkGroup, vk_user_id: int, ref: str | None = None,
) -> Client:
    client = await db.scalar(
        select(Client).where(
            Client.vk_group_id == group.id,
            Client.vk_user_id == vk_user_id,
        )
    )
    if not client:
        client = Client(
            vk_user_id=vk_user_id,
            vk_group_id=group.id,
            source=f"vk:{group.group_id}",
            # Тег ref-ссылки = marketing_tag скриптов ('sweetgold', 'ПАВЕЛ_ПАТРИОТ_1'),
            # по нему list_scripts отбирает приветствие под конкретную рекламу.
            # Сравнение в format_scripts_list точное — сохраняем как прислал ВК.
            marketing_tags=[ref] if ref else None,
        )
        db.add(client)
        await db.flush()
        if ref:
            logger.info("[vk=%s/%s] client tagged by ref=%r", group.group_id, vk_user_id, ref)
    elif ref and not client.marketing_tags:
        # Клиент уже заведён, но без тега (пришёл до подключения ref-ссылок либо
        # первое сообщение потерялось) — проставляем задним числом.
        client.marketing_tags = [ref]
        await db.flush()
        logger.info("[vk=%s/%s] client back-tagged by ref=%r", group.group_id, vk_user_id, ref)
    return client


async def _get_or_create_dialog(
    db: AsyncSession, client: Client, type_id: int | None, ai_allowed: bool = True,
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
        # Метка не в белом списке — диалог сразу к живому менеджеру, ИИ молчит.
        ai_paused=not ai_allowed,
        ai_provider=pick_ai_provider(client.id),
    )
    db.add(dialog)
    await db.flush()
    return dialog


async def handle_message_new(db: AsyncSession, group: VkGroup, msg: VkIncomingMessage) -> None:
    """Входящее сообщение пользователя: сохранить, запустить ИИ, отправить ответ."""
    client = await _get_or_create_client(db, group, msg.vk_user_id, ref=msg.ref)
    type_id, type_name = await _resolve_dialog_type(db, group)
    current_dialog_type.set(type_name)

    from app.sales.ref_tags import RefTagService
    client_tag = (client.marketing_tags or [None])[0]
    ai_allowed = await RefTagService(db).ai_allowed(client_tag, type_id)
    dialog = await _get_or_create_dialog(db, client, type_id, ai_allowed=ai_allowed)
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
        if msg.files or msg.audio_urls or msg.sticker_files:
            msg_metadata = {}
            if msg.files:
                msg_metadata["files"] = msg.files
            if msg.audio_urls:
                msg_metadata["audio_urls"] = msg.audio_urls
            if msg.sticker_files:
                msg_metadata["sticker_files"] = msg.sticker_files
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

    from app.ai.dialog_lock import dialog_lock, superseded_by_newer_message

    # Один прогон на диалог за раз. Клиент пишет вторую реплику, не дождавшись
    # ответа на первую, а прогон идёт десятки секунд — без блокировки получалось
    # два параллельных прогона и два ответа подряд (диалог 74).
    async with dialog_lock(dialog.id):
        await db.refresh(dialog)
        if dialog.ai_paused:
            logger.info("[%s] ai paused (operator took over) — message saved, no AI run", ctx)
            return
        if await superseded_by_newer_message(db, dialog.id, client_message.id):
            logger.info("[%s] newer client message arrived — this turn yields", ctx)
            return

        await _reply_with_ai(db, dialog, client_message, ctx)


async def _reply_with_ai(
    db: AsyncSession, dialog: Dialog, client_message: Message, ctx: str,
) -> None:
    """Прогон модели и отправка всех реплик хода. Вызывается под блокировкой диалога."""
    from app.ai.runner import run_ai
    output, ai_run, parts = await run_ai(db, dialog, client_message)

    if output.need_curator:
        # Пауза диалога проставлена в run_ai — здесь только придерживаем ответ.
        logger.info("[%s] need_curator=True — reply held for review", ctx)
        return

    from app.vk.sender import VkApiError, VkMessagesForbiddenError, send_to_dialog
    sent = 0
    for i, part in enumerate(parts):
        if not part.text and not part.image_urls:
            logger.info("[%s] empty reply part %d — skipped", ctx, i)
            continue
        # Фото-вложения через VK upload API пока не поддержаны — URL уходят текстом,
        # ВК сам рендерит превью ссылок.
        outgoing_text = part.text or ""
        if part.image_urls:
            outgoing_text = (outgoing_text + "\n" + "\n".join(part.image_urls)).strip()

        if sent:
            # Связка скриптов уходит двумя сообщениями подряд. Лимитам ВК это не
            # мешает (20 запросов/сек на токен сообщества), пауза нужна, чтобы
            # реплики не приходили одной миллисекундой и читались по-человечески.
            await asyncio.sleep(FOLLOW_UP_DELAY_SECONDS)

        try:
            vk_message_id = await send_to_dialog(db, dialog, outgoing_text)
        except VkMessagesForbiddenError:
            await db.commit()  # vk_blocked проставлен в send_to_dialog
            return
        except (VkApiError, Exception):
            logger.exception("[%s] vk reply send failed | part=%d", ctx, i)
            break

        # Проставляем VK id на исходящее сообщение: message_reply о нашей же отправке
        # придёт в вебхук, и по этому id (и random_id≠0) мы его отличим от оператора.
        if vk_message_id and not part.message.external_message_id:
            part.message.external_message_id = str(vk_message_id)
        sent += 1
        logger.info(
            "[%s] vk reply sent | part=%d/%d | vk_message_id=%s",
            ctx, i + 1, len(parts), vk_message_id,
        )

    if sent:
        dialog.last_message_at = msk_now()
    await db.commit()


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
