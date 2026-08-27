"""Ответы менеджера в MAX, ушедшие мимо панели.

MAX не присылает событий о сообщениях, отправленных от имени бота, — ни своих,
ни чужих. Единственный источник — история диалога, и весь смысл этих проверок в
том, чтобы своё же в ней не сойти за менеджера и наоборот.
"""
import pytest
from sqlalchemy import select

from app.db.models import (
    Client, Dialog, DialogPingState, DialogType, Message, MessageRole, VkGroup,
)
from app.max.manager_watch import (
    chat_id_from_mid, pause_if_manager_replied, remember_chat_id, watch_once,
)
from app.utils.time import msk_now
from app.vk.outgoing import MAX_MIDS

BOT_ID = 777001
USER_ID = 555
CHAT_ID = 900
# 27.08.2026, 10:00 МСК и далее — время в истории MAX приходит в миллисекундах.
BASE_TS = 1787814000000


@pytest.fixture
async def max_bot(db):
    dt = DialogType(name="clothes", display_name="Одежда")
    db.add(dt)
    await db.flush()
    bot = VkGroup(
        platform="max", group_id=BOT_ID, name="Хэмилтон", username="hemilton_bot",
        access_token="max-token", secret_key="s3cret-max", dialog_type_id=dt.id,
        webhook_subscribed=True, is_active=True,
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return bot


@pytest.fixture
async def dialog(db, max_bot):
    client = Client(
        vk_user_id=USER_ID, vk_group_id=max_bot.id, name="Евгений", max_chat_id=CHAT_ID,
    )
    db.add(client)
    await db.flush()
    d = Dialog(client_id=client.id, type_id=max_bot.dialog_type_id)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


@pytest.fixture
def same_session(db, monkeypatch):
    """Наблюдатель открывает свою сессию — в тестах отдаём ту же самую."""
    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", lambda: _Ctx())


class _History(list):
    """История MAX: тест кладёт сюда сообщения, `calls` считает обращения."""

    calls: list

    def __init__(self):
        super().__init__()
        self.calls = []


@pytest.fixture
def history(monkeypatch):
    entries = _History()

    async def _get_messages(token, chat_id, count=10):
        entries.calls.append(chat_id)
        # MAX отдаёт последние сообщения первыми.
        return list(reversed(entries))[:count]

    monkeypatch.setattr("app.max.client.get_messages", _get_messages)
    return entries


def _entry(*, mid, text="", ts=BASE_TS, from_bot=True, attachments=None, user_id=USER_ID):
    """Одна запись истории MAX."""
    return {
        "sender": {"user_id": BOT_ID if from_bot else user_id, "is_bot": from_bot},
        "recipient": {
            "chat_id": CHAT_ID, "chat_type": "dialog",
            "user_id": user_id if from_bot else BOT_ID,
        },
        "timestamp": ts,
        "body": {"mid": mid, "seq": 1, "text": text, "attachments": attachments or []},
    }


async def _our_message(db, dialog, *, text, mid, extra_mids=None, when=None):
    meta = {"delivered": True}
    if extra_mids:
        meta[MAX_MIDS] = extra_mids
    msg = Message(
        dialog_id=dialog.id, role=MessageRole.ai, text=text,
        external_message_id=mid, created_at=when or msk_now(), msg_metadata=meta,
    )
    db.add(msg)
    await db.commit()
    return msg


async def _curator_messages(db, dialog):
    rows = await db.execute(
        select(Message).where(
            Message.dialog_id == dialog.id, Message.role == MessageRole.curator,
        ).order_by(Message.id)
    )
    return list(rows.scalars().all())


# --- chat_id ------------------------------------------------------------------


def test_chat_id_restored_from_mid():
    """Диалогам, заведённым до колонки, chat_id достаётся из mid сообщения."""
    assert chat_id_from_mid("mid.0000000010740f8601a0422d3d544a72") == 276041606


@pytest.mark.parametrize("mid", [None, "", "12345", "mid.short", "mid." + "z" * 32])
def test_chat_id_from_junk_is_none(mid):
    assert chat_id_from_mid(mid) is None


async def test_chat_id_remembered_from_webhook(db, max_bot, dialog):
    """chat_id из входящего события сохраняется — по нему потом читаем историю."""
    client = await db.get(Client, dialog.client_id)
    client.max_chat_id = None
    await db.commit()

    await remember_chat_id(db, max_bot, USER_ID, CHAT_ID)
    await db.commit()

    await db.refresh(client)
    assert client.max_chat_id == CHAT_ID


# --- перехват диалога менеджером ----------------------------------------------


async def test_manager_reply_recorded_and_ai_paused(db, max_bot, dialog, history, same_session):
    """Чужая реплика бота попадает в панель, гасит ИИ и пинги."""
    await _our_message(db, dialog, text="Стоимость 5 990 ₽", mid="mid.ours-1")
    db.add(DialogPingState(dialog_id=dialog.id, funnel_type="knows_price", current_step=1))
    await db.commit()
    history.extend([
        _entry(mid="mid.ours-1", text="Стоимость 5 990 ₽", ts=BASE_TS),
        _entry(mid="mid.manager-1", text="Согласовала для Вас скидку", ts=BASE_TS + 60000),
    ])

    assert await pause_if_manager_replied(dialog.id) is True

    await db.refresh(dialog)
    assert dialog.ai_paused is True
    recorded = await _curator_messages(db, dialog)
    assert [m.text for m in recorded] == ["Согласовала для Вас скидку"]
    assert recorded[0].external_message_id == "mid.manager-1"
    assert recorded[0].msg_metadata["max_operator"] is True
    state = await db.scalar(select(DialogPingState).where(DialogPingState.dialog_id == dialog.id))
    assert state.is_completed is True


async def test_manager_photo_recorded_as_attachment_token(db, max_bot, dialog, history, same_session):
    """Картинку менеджера панель показывает картинкой, а не строкой «[вложение]»."""
    await _our_message(db, dialog, text="Стоимость 5 990 ₽", mid="mid.ours-1")
    history.extend([
        _entry(mid="mid.ours-1", text="Стоимость 5 990 ₽", ts=BASE_TS),
        _entry(
            mid="mid.manager-1", text="Ваш макет", ts=BASE_TS + 60000,
            attachments=[{"type": "image", "payload": {"url": "https://i.oneme.ru/i?r=abc"}}],
        ),
    ])

    assert await pause_if_manager_replied(dialog.id) is True

    recorded = await _curator_messages(db, dialog)
    assert recorded[0].text == "Ваш макет\n[photo-https://i.oneme.ru/i?r=abc]"


async def test_recorded_reply_is_not_recorded_twice(db, max_bot, dialog, history, same_session):
    """Повторный проход по той же истории новых сообщений не заводит."""
    await _our_message(db, dialog, text="Стоимость 5 990 ₽", mid="mid.ours-1")
    history.extend([
        _entry(mid="mid.ours-1", text="Стоимость 5 990 ₽", ts=BASE_TS),
        _entry(mid="mid.manager-1", text="Согласовала для Вас скидку", ts=BASE_TS + 60000),
    ])

    assert await pause_if_manager_replied(dialog.id) is True
    assert await pause_if_manager_replied(dialog.id) is False
    assert len(await _curator_messages(db, dialog)) == 1


async def test_dialog_without_our_messages_is_taken_over(db, max_bot, dialog, history, same_session):
    """Карточка без единого нашего сообщения: всё, что в MAX, — работа менеджера.

    Ровно случай из скриншота ОП: клиент нажал «Начать», ИИ по метке не
    отвечает, переписку с 09:51 ведёт менеджер, а у нас по диалогу пусто.
    """
    history.append(_entry(mid="mid.manager-1", text="Здравствуйте! Меня зовут София", ts=BASE_TS))

    assert await pause_if_manager_replied(dialog.id) is True

    await db.refresh(dialog)
    assert dialog.ai_paused is True
    assert len(await _curator_messages(db, dialog)) == 1


# --- своё за чужое не принимаем -----------------------------------------------


async def test_own_chunk_without_mid_is_not_a_manager(db, max_bot, dialog, history, same_session):
    """MAX возвращает mid только последнего куска — остальные узнаём по тексту."""
    await _our_message(
        db, dialog, text="Первая часть текста. Вторая часть текста.", mid="mid.ours-2",
    )
    history.extend([
        _entry(mid="mid.ours-2", text="Вторая часть текста.", ts=BASE_TS + 61000),
        _entry(mid="mid.chunk-1", text="Первая часть текста.", ts=BASE_TS + 62000),
    ])

    assert await pause_if_manager_replied(dialog.id) is False
    assert await _curator_messages(db, dialog) == []


async def test_own_chunks_known_by_saved_mids(db, max_bot, dialog, history, same_session):
    """Все mid отправки сохраняются — по ним свои куски узнаются и без текста."""
    await _our_message(
        db, dialog, text="Каталог", mid="mid.ours-2", extra_mids=["mid.ours-1", "mid.ours-2"],
    )
    history.extend([
        _entry(mid="mid.ours-1", text="", ts=BASE_TS + 60000,
               attachments=[{"type": "image", "payload": {"url": "https://i.oneme.ru/i?r=x"}}]),
        _entry(mid="mid.ours-2", text="Каталог", ts=BASE_TS + 61000),
    ])

    assert await pause_if_manager_replied(dialog.id) is False


async def test_reply_older_than_our_last_message_is_ignored(db, max_bot, dialog, history, same_session):
    """Реплика до нашего последнего сообщения — прошлое, а не перехват."""
    await _our_message(db, dialog, text="Стоимость 5 990 ₽", mid="mid.ours-2")
    history.extend([
        _entry(mid="mid.manager-old", text="Добрый день", ts=BASE_TS),
        _entry(mid="mid.ours-2", text="Стоимость 5 990 ₽", ts=BASE_TS + 60000),
    ])

    assert await pause_if_manager_replied(dialog.id) is False
    assert await _curator_messages(db, dialog) == []


async def test_history_of_another_client_is_ignored(db, max_bot, dialog, history, same_session):
    """Угаданный chat_id проверяем по участникам: чужая переписка в карточку не попадёт."""
    client = await db.get(Client, dialog.client_id)
    client.max_chat_id = None
    await db.commit()
    await _our_message(db, dialog, text="Стоимость", mid="mid.0000000010740f8601a0422d3d544a72")
    history.append(_entry(mid="mid.stranger", text="Чужая переписка", ts=BASE_TS + 60000, user_id=999))

    assert await pause_if_manager_replied(dialog.id) is False
    assert await _curator_messages(db, dialog) == []
    await db.refresh(client)
    assert client.max_chat_id is None


async def test_client_messages_are_not_a_takeover(db, max_bot, dialog, history, same_session):
    """Сообщения самого клиента диалог не перехватывают."""
    await _our_message(db, dialog, text="Стоимость 5 990 ₽", mid="mid.ours-1")
    history.extend([
        _entry(mid="mid.ours-1", text="Стоимость 5 990 ₽", ts=BASE_TS),
        _entry(mid="mid.client-1", text="Дорого", ts=BASE_TS + 60000, from_bot=False),
    ])

    assert await pause_if_manager_replied(dialog.id) is False


async def test_vk_dialog_does_not_reach_max_api(db, dialog, history, same_session):
    """Диалог ВК проверять в MAX незачем — до чтения истории дело не доходит."""
    client = await db.get(Client, dialog.client_id)
    group = await db.get(VkGroup, client.vk_group_id)
    group.platform = "vk"
    await db.commit()

    assert await pause_if_manager_replied(dialog.id) is False
    assert history.calls == []


# --- фоновый проход -----------------------------------------------------------


async def test_watch_once_scans_recent_dialogs(db, max_bot, dialog, history, same_session):
    """Проход находит перехват и без единого входящего сообщения от клиента."""
    dialog.last_message_at = msk_now()
    await db.commit()
    history.append(_entry(mid="mid.manager-1", text="Я уже с ним общаюсь", ts=BASE_TS))

    await watch_once()

    await db.refresh(dialog)
    assert dialog.ai_paused is True
    assert [m.text for m in await _curator_messages(db, dialog)] == ["Я уже с ним общаюсь"]


async def test_watch_once_skips_blocked_dialog(db, max_bot, dialog, history, same_session):
    """Клиент остановил бота — читать историю незачем."""
    dialog.vk_blocked = True
    dialog.last_message_at = msk_now()
    await db.commit()
    history.append(_entry(mid="mid.manager-1", text="Я уже с ним общаюсь", ts=BASE_TS))

    await watch_once()

    assert history.calls == []
    assert await _curator_messages(db, dialog) == []
