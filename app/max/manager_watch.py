"""Ответы менеджера, ушедшие мимо нас: MAX о них не рассказывает.

Бот MAX — один аккаунт на всех, кто из него пишет. К боту Hemilton подключена
не только эта панель, но и Wazzup (`max-bot.wazzup24.com` в списке подписок
бота) — из него менеджеры ОП отвечают клиенту от имени того же бота. События о
таком сообщении не приходит НИКОМУ: `message_created` MAX присылает только о
входящих, а исходящие бота — чьей бы рукой они ни были отправлены — остаются
между MAX и клиентом. Поэтому `app.max.webhook.handle_bot_message` за трое
суток на проде не сработал ни разу: сообщений с ролью curator в MAX-диалогах
нет вовсе, хотя в истории самого MAX их десятки.

Отсюда две беды, о которых ОП сообщил 27.08: «через бс клиенту ответила 4 мин
назад, в панели мои сообщения не отобразились еще, как будто все так же ии
работает». Реплик менеджера в панели не видно, диалог считается ведомым ИИ — и
ИИ пишет поверх менеджера (диалог 79820: менеджер вёл клиента с 08:59 до 09:26,
в 09:26:42 ИИ поздоровался заново).

Раз события нет, историю спрашиваем сами: `GET /messages?chat_id=…` для личного
диалога отдаёт всё, включая исходящие. Работает это в двух режимах:

- `watch_once` — фоновый проход по свежим диалогам: чужие реплики попадают в
  панель и гасят ИИ, даже если клиент после них ничего не написал;
- `pause_if_manager_replied` — проверка прямо перед отправкой: между проходами
  воркера ход ИИ или пинг успевает перебить менеджера.

Чужим считается сообщение бота, которого нет среди наших И которое новее
последнего опознанного нашего (см. `_partition`): mid MAX возвращает только на
ПОСЛЕДНИЙ кусок длинного текста, поэтому предыдущие куски своих же отправок в
истории безымянны и без этого правила выглядели бы чужими.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Client, Dialog, Message, MessageRole, VkGroup
from app.utils.time import msk_now, to_naive_msk

logger = logging.getLogger(__name__)

# Сколько последних сообщений диалога читаем. Перед отправкой хватает короткого
# хвоста, фоновому проходу нужен запас на серию реплик менеджера.
_GUARD_HISTORY = 10
_WATCH_HISTORY = 30
# Сколько наших последних исходящих держим для опознания своих же кусков.
_OUR_LOOKBACK = 40
# Запас на серию: длинный текст уходит несколькими сообщениями уже ПОСЛЕ того,
# как строка появилась в базе. Без этого зазора собственные куски без mid
# оказывались бы новее отметки и читались как ответ менеджера.
_OWN_BURST_SECONDS = 180
# Столько диалогов MAX проверяем за один проход, самые свежие вперёд.
_WATCH_BATCH = 300
# Одновременных запросов к MAX. Потолок платформы — 30 запросов в секунду на
# токен; четыре параллельных чтения оставляют его свободным для отправок.
_WATCH_CONCURRENCY = 4

_MID_PREFIX = "mid."
# Текст, которым записывается реплика менеджера без текста (одно вложение).
_ATTACHMENT_ONLY = "[вложение]"


def chat_id_from_mid(mid: str | None) -> int | None:
    """Достать chat_id из идентификатора сообщения MAX.

    Запасной путь для диалогов, заведённых до того, как мы начали запоминать
    `recipient.chat_id` из вебхука. Идентификатор выглядит как
    `mid.0000000010740f8601a0422d3d544a72`: восемь нулей, затем chat_id в hex,
    затем метка самого сообщения. На боевой базе это подтверждается ровно —
    1001 сообщение, 211 диалогов, у каждого диалога hex один и тот же.

    Догадка про формат ничем не документирована, поэтому результат обязательно
    проверяется по ответу MAX (`_history_belongs_to`), прежде чем попасть в базу.
    """
    if not mid or not mid.startswith(_MID_PREFIX):
        return None
    body = mid[len(_MID_PREFIX):]
    if len(body) < 16:
        return None
    try:
        return int(body[8:16], 16) or None
    except ValueError:
        return None


def _sender_id(entry: dict) -> int | None:
    sender = entry.get("sender") or {}
    user_id = sender.get("user_id")
    return int(user_id) if user_id is not None and sender.get("is_bot") else None


def _entry_mid(entry: dict) -> str | None:
    mid = (entry.get("body") or {}).get("mid")
    return str(mid) if mid is not None else None


def _entry_time(entry: dict) -> int:
    return int(entry.get("timestamp") or 0)


def _entry_text(entry: dict) -> str:
    """Текст реплики вместе с вложениями — в том же виде, что и у скриптов.

    Панель показывает картинку по токену `[photo-<ссылка>]` (см.
    frontend/src/pages/ChatPage.vue), поэтому фотографии менеджера доходят до
    менеджерской панели картинками, а не строкой «[вложение]».
    """
    body = entry.get("body") or {}
    text = (body.get("text") or "").strip()
    tokens = []
    for att in body.get("attachments") or []:
        url = (att.get("payload") or {}).get("url")
        kind = {"image": "photo", "video": "video"}.get(att.get("type"), "doc")
        tokens.append(f"[{kind}-{url}]" if url else _ATTACHMENT_ONLY)
    if tokens:
        return (text + "\n" + "\n".join(tokens)).strip()
    return text


def _normalized(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _looks_like_ours(text: str, our_texts: list[str]) -> bool:
    """Наш же текст, только без mid.

    Длинный ответ MAX режет на куски по 4000 символов, а mid возвращает лишь на
    последний. Кусок — это всегда часть текста, который лежит у нас в базе, по
    ней его и узнаём.
    """
    normalized = _normalized(text)
    if not normalized:
        return False
    return any(normalized in ours for ours in our_texts if ours)


def _msk_from_ms(ms: int) -> datetime:
    return to_naive_msk(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))


def _ms_from_msk(dt: datetime | None) -> int:
    if dt is None:
        return 0
    return int(dt.replace(tzinfo=timezone(timedelta(hours=3))).timestamp() * 1000)


async def _our_outgoing(db: AsyncSession, dialog_id: int) -> tuple[set[str], list[str], datetime | None]:
    """Наши исходящие этого диалога: их mid, тексты и время последнего."""
    from app.vk.outgoing import MAX_MIDS

    rows = await db.execute(
        select(Message.external_message_id, Message.msg_metadata, Message.text, Message.created_at)
        .where(Message.dialog_id == dialog_id, Message.role != MessageRole.client)
        .order_by(Message.id.desc())
        .limit(_OUR_LOOKBACK)
    )
    mids: set[str] = set()
    texts: list[str] = []
    last_at: datetime | None = None
    for external_id, meta, text, created_at in rows.all():
        if external_id:
            mids.add(external_id)
        mids.update((meta or {}).get(MAX_MIDS) or [])
        if (meta or {}).get("max_operator"):
            # Уже записанная реплика менеджера. Её mid держим (по нему работает
            # дедуп), а текст — нет: иначе повторное «?» менеджера сочлось бы
            # нашим и в панель не попало.
            continue
        texts.append(_normalized(text))
        if created_at and (last_at is None or created_at > last_at):
            last_at = created_at
    return mids, texts, last_at


def _partition(
    history: list[dict], bot_id: int, mids: set[str], our_texts: list[str],
    our_last_at: datetime | None,
) -> list[dict]:
    """Чужие реплики бота: не наши и новее последней опознанной нашей.

    Отметка времени обязательна. Без неё в чужие попали бы безымянные куски
    наших же длинных отправок, и ИИ вставал бы на паузу сам от себя.
    """
    ours_seen_at = 0
    for entry in history:
        if _sender_id(entry) != bot_id:
            continue
        if _entry_mid(entry) in mids or _looks_like_ours(_entry_text(entry), our_texts):
            ours_seen_at = max(ours_seen_at, _entry_time(entry))

    if not ours_seen_at and our_last_at is not None:
        # Своих реплик в прочитанном окне не нашлось, хотя в базе они есть:
        # окно короче паузы в переписке. Отсчитываем от последней записи в базе
        # с запасом на серию — иначе чужим окажется всё окно разом.
        ours_seen_at = _ms_from_msk(our_last_at) + _OWN_BURST_SECONDS * 1000

    foreign = [
        entry for entry in history
        if _sender_id(entry) == bot_id
        and _entry_time(entry) > ours_seen_at
        and _entry_mid(entry) not in mids
        and not _looks_like_ours(_entry_text(entry), our_texts)
    ]
    return sorted(foreign, key=_entry_time)


def _history_belongs_to(history: list[dict], bot_id: int, user_id: int) -> bool:
    """Это точно переписка бота именно с этим клиентом.

    Проверка нужна там, где chat_id угадан из mid: чужая история молча привязала
    бы к карточке реплики другого клиента.
    """
    allowed = {int(bot_id), int(user_id)}
    for entry in history:
        for side in ((entry.get("sender") or {}), (entry.get("recipient") or {})):
            uid = side.get("user_id")
            if uid is not None and int(uid) not in allowed:
                return False
    return bool(history)


async def _chat_id_for(db: AsyncSession, client: Client, dialog_id: int) -> tuple[int | None, bool]:
    """chat_id диалога и признак «значение угадано, требует проверки»."""
    if client.max_chat_id:
        return int(client.max_chat_id), False
    mid = await db.scalar(
        select(Message.external_message_id)
        .where(
            Message.dialog_id == dialog_id,
            Message.external_message_id.like(f"{_MID_PREFIX}%"),
        )
        .order_by(Message.id.desc())
        .limit(1)
    )
    return chat_id_from_mid(mid), True


async def remember_chat_id(db: AsyncSession, bot: VkGroup, user_id: int, chat_id) -> None:
    """Запомнить chat_id из вебхука: по нему потом читается история диалога.

    MAX не умеет отдавать историю по user_id («ChatId & messageIds not found in
    request»), а список чатов для личных диалогов пуст — chat_id можно взять
    только из входящего события.
    """
    if chat_id is None:
        return
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return
    client = await db.scalar(
        select(Client).where(Client.vk_group_id == bot.id, Client.vk_user_id == int(user_id))
    )
    if client is not None and client.max_chat_id != chat_id:
        client.max_chat_id = chat_id
        await db.flush()


async def _record(db: AsyncSession, dialog: Dialog, foreign: list[dict], ctx: str) -> int:
    """Записать чужие реплики в диалог, погасить ИИ и пинги."""
    from app.ping.worker import stop_pings

    for entry in foreign:
        sent_at = _entry_time(entry)
        db.add(Message(
            dialog_id=dialog.id,
            role=MessageRole.curator,
            text=_entry_text(entry) or _ATTACHMENT_ONLY,
            external_message_id=_entry_mid(entry),
            created_at=_msk_from_ms(sent_at) if sent_at else msk_now(),
            msg_metadata={"max_operator": True, "delivered": True},
        ))
    latest = _entry_time(foreign[-1])
    if latest:
        sent_at = _msk_from_ms(latest)
        if dialog.last_message_at is None or sent_at > dialog.last_message_at:
            dialog.last_message_at = sent_at
    if not dialog.ai_paused:
        dialog.ai_paused = True
        logger.info("[%s] менеджер ответил мимо панели — ИИ на паузе", ctx)
    await stop_pings(db, dialog.id, "менеджер ответил в MAX мимо панели")
    return len(foreign)


async def _fetch(token: str, chat_id: int, count: int) -> list[dict] | None:
    from app.max.client import MaxApiError, get_messages

    try:
        return await get_messages(token, chat_id, count=count)
    except MaxApiError as exc:
        logger.info("история MAX недоступна | chat_id=%s: %s", chat_id, exc)
    except Exception as exc:
        logger.warning("чтение истории MAX не удалось | chat_id=%s: %s", chat_id, exc)
    return None


async def _check_dialog(
    db: AsyncSession, dialog: Dialog, client: Client, bot: VkGroup, count: int,
    history: list[dict] | None = None, chat_id: int | None = None, guessed: bool = False,
) -> int:
    """Одна сверка диалога с историей MAX. Возвращает число новых чужих реплик.

    `history` и `chat_id` передаются, когда их уже добыли пачкой (фоновый проход).
    """
    ctx = f"max={bot.group_id}/{client.vk_user_id}"
    if chat_id is None:
        chat_id, guessed = await _chat_id_for(db, client, dialog.id)
    if chat_id is None:
        return 0
    if history is None:
        history = await _fetch(bot.access_token, chat_id, count)
    if not history:
        return 0
    if not _history_belongs_to(history, int(bot.group_id), int(client.vk_user_id or 0)):
        logger.warning("[%s] история chat_id=%s не о нём — пропускаем", ctx, chat_id)
        return 0
    if guessed:
        client.max_chat_id = chat_id

    mids, our_texts, our_last_at = await _our_outgoing(db, dialog.id)
    foreign = _partition(history, int(bot.group_id), mids, our_texts, our_last_at)
    if not foreign:
        return 0
    logger.info(
        "[%s] в MAX %d реплик мимо панели | dialog=%s", ctx, len(foreign), dialog.id,
    )
    return await _record(db, dialog, foreign, ctx)


async def pause_if_manager_replied(dialog_id: int) -> bool:
    """Проверка перед отправкой: не отвечает ли клиенту живой менеджер.

    Идёт в собственной сессии: вызывают её из середины чужого хода (ответ ИИ,
    пинг, догоняющая цена), и пауза с записью реплик менеджера не должна
    исчезнуть, если этот ход потом откатится.
    """
    if not settings.MAX_MANAGER_WATCH_ENABLED:
        return False
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            dialog = await db.get(Dialog, dialog_id)
            if dialog is None or dialog.vk_blocked:
                return False
            client = await db.get(Client, dialog.client_id)
            if client is None or not client.vk_group_id or not client.vk_user_id:
                return False
            bot = await db.get(VkGroup, client.vk_group_id)
            if bot is None or (bot.platform or "vk") != "max" or not bot.access_token:
                return False
            found = await _check_dialog(db, dialog, client, bot, _GUARD_HISTORY)
            await db.commit()
            return bool(found)
    except Exception as exc:
        # Проверка не должна ронять отправку: не дочитались до MAX — работаем
        # как раньше, фоновый проход поймает перехват следующим кругом.
        logger.warning("проверка ответа менеджера не удалась | dialog=%s: %s", dialog_id, exc)
        return False


async def watch_once() -> None:
    """Один проход по свежим диалогам MAX."""
    if not settings.MAX_MANAGER_WATCH_ENABLED:
        return
    from app.db.session import AsyncSessionLocal

    window = msk_now() - timedelta(hours=settings.MAX_MANAGER_WATCH_WINDOW_HOURS)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Dialog, Client, VkGroup)
            .join(Client, Dialog.client_id == Client.id)
            .join(VkGroup, Client.vk_group_id == VkGroup.id)
            .where(
                VkGroup.platform == "max",
                VkGroup.is_active == True,  # noqa: E712 — SQL-выражение
                Dialog.vk_blocked == False,  # noqa: E712
                Client.vk_user_id.isnot(None),
                (Dialog.last_message_at >= window) | (
                    Dialog.last_message_at.is_(None) & (Dialog.created_at >= window)
                ),
            )
            .order_by(Dialog.last_message_at.desc().nulls_last())
            .limit(_WATCH_BATCH)
        )).all()

        if not rows:
            return

        # chat_id достаётся из базы, поэтому все обращения к сессии — до
        # параллельного чтения: одну AsyncSession нельзя делить между задачами.
        prepared = []
        for dialog, client, bot in rows:
            if not bot.access_token:
                continue
            chat_id, guessed = await _chat_id_for(db, client, dialog.id)
            if chat_id is None:
                continue
            prepared.append((dialog, client, bot, chat_id, guessed))

        semaphore = asyncio.Semaphore(_WATCH_CONCURRENCY)

        async def _load(token: str, chat_id: int):
            async with semaphore:
                return await _fetch(token, chat_id, _WATCH_HISTORY)

        histories = await asyncio.gather(
            *(_load(bot.access_token, chat_id) for _d, _c, bot, chat_id, _g in prepared)
        )

        found = 0
        for (dialog, client, bot, chat_id, guessed), history in zip(prepared, histories):
            if not history:
                continue
            try:
                found += await _check_dialog(
                    db, dialog, client, bot, _WATCH_HISTORY,
                    history=history, chat_id=chat_id, guessed=guessed,
                )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.error(
                    "сверка с историей MAX не удалась | dialog=%s: %s",
                    dialog.id, exc, exc_info=True,
                )
        logger.info(
            "проверено диалогов MAX: %d, записано реплик мимо панели: %d",
            len(prepared), found,
        )
