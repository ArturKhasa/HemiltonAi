"""Вебхук MAX: разбор события, общий путь обработки, «Начать» и остановка бота."""
import importlib

import pytest
from sqlalchemy import select

from app.ai.runner import ReplyPart
from app.ai.schemas import AgentOutput
from app.db.models import (
    AIRun, Client, Dialog, DialogPingState, DialogType, Message, MessageRole, Script, VkGroup,
)
from app.max.client import MaxSentMessage
from app.max.webhook import (
    handle_bot_message, handle_bot_stopped, handle_dialog_removed,
    handle_start,
    pause_if_first_message_has_manager_reply,
    parse_message_created,
    start_command,
)
from app.vk.webhook import handle_message_new


@pytest.fixture
async def max_bot(db):
    dt = DialogType(name="clothes", display_name="Одежда")
    db.add(dt)
    await db.flush()
    bot = VkGroup(
        platform="max",
        group_id=777001,
        name="Хэмилтон",
        username="hemilton_bot",
        access_token="max-token",
        secret_key="s3cret-max",
        dialog_type_id=dt.id,
        webhook_subscribed=True,
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return bot


def _message_created(
    *, user_id=555, text="Здравствуйте, есть размер M?", mid="mid-1",
    attachments=None, first_name="Анастасия", last_name="Петрова", is_bot=False,
):
    return {
        "update_type": "message_created",
        "timestamp": 1770000000000,
        "message": {
            "sender": {
                "user_id": user_id,
                "first_name": first_name,
                "last_name": last_name,
                "is_bot": is_bot,
            },
            "recipient": {"chat_id": 900, "chat_type": "dialog", "user_id": 777001},
            "timestamp": 1770000000000,
            "body": {"mid": mid, "seq": 1, "text": text, "attachments": attachments or []},
        },
        "user_locale": "ru",
    }


def _bot_message_created(*, user_id=555, text="Макет готов", mid="manager-mid"):
    """Сообщение, отправленное от имени бота внешним интерфейсом менеджера."""
    return {
        "update_type": "message_created",
        "timestamp": 1770000000000,
        "message": {
            "sender": {"user_id": 777001, "is_bot": True},
            "recipient": {"chat_id": 900, "chat_type": "dialog", "user_id": user_id},
            "timestamp": 1770000000000,
            "body": {"mid": mid, "seq": 1, "text": text, "attachments": []},
        },
    }


# --- Разбор события -----------------------------------------------------------


def test_parse_plain_text():
    msg = parse_message_created(_message_created())
    assert msg.vk_user_id == 555
    assert msg.peer_id == 555
    assert msg.text == "Здравствуйте, есть размер M?"
    assert msg.external_message_id == "mid-1"
    assert (msg.first_name, msg.last_name) == ("Анастасия", "Петрова")


def test_parse_skips_bot_sender():
    assert parse_message_created(_message_created(is_bot=True)) is None


def test_parse_photo_without_text():
    msg = parse_message_created(_message_created(
        text="", attachments=[{"type": "image", "payload": {"url": "https://cdn/1.jpg"}}],
    ))
    assert msg.files == ["https://cdn/1.jpg"]
    assert msg.text == "[фото]"


def test_parse_voice_uses_max_transcription():
    """MAX расшифровывает голосовые сам — свой Whisper тогда не нужен."""
    msg = parse_message_created(_message_created(text="", attachments=[{
        "type": "audio",
        "payload": {"url": "https://cdn/voice.mp3"},
        "transcription": "Хочу свитшот на двоих",
    }]))
    assert msg.text == "Хочу свитшот на двоих"
    assert msg.audio_urls == []


def test_parse_voice_without_transcription_keeps_url():
    msg = parse_message_created(_message_created(text="", attachments=[
        {"type": "audio", "payload": {"url": "https://cdn/voice.mp3"}},
    ]))
    assert msg.text == "[голосовое сообщение]"
    assert msg.audio_urls == ["https://cdn/voice.mp3"]


def test_parse_sticker_and_file_marks():
    msg = parse_message_created(_message_created(text="спасибо", attachments=[
        {"type": "sticker", "payload": {"url": "https://cdn/s.png"}, "width": 1, "height": 1},
        {"type": "file", "payload": {"url": "https://cdn/check.pdf"}, "filename": "чек.pdf", "size": 10},
    ]))
    assert "[Стикер]" in msg.text and "[файл: чек.pdf]" in msg.text
    assert msg.sticker_files == ["https://cdn/s.png"]
    assert msg.files == ["https://cdn/check.pdf"]


def test_parse_empty_event_returns_none():
    assert parse_message_created(_message_created(text="", attachments=[])) is None


# --- Эндпоинт -----------------------------------------------------------------


async def test_webhook_unknown_bot_404(client, db):
    resp = await client.post("/webhook/max/999", json=_message_created())
    assert resp.status_code == 404


async def test_webhook_bad_secret_403(client, max_bot):
    max_bot.is_active = True
    resp = await client.post(
        f"/webhook/max/{max_bot.id}",
        json=_message_created(),
        headers={"X-Max-Bot-Api-Secret": "wrong"},
    )
    assert resp.status_code == 403


async def test_webhook_acks_and_schedules(client, db, max_bot, monkeypatch):
    max_bot.is_active = True
    await db.commit()
    scheduled = []
    monkeypatch.setattr(
        "app.api.max.schedule_event", lambda pk, payload: scheduled.append((pk, payload)),
    )
    resp = await client.post(
        f"/webhook/max/{max_bot.id}",
        json=_message_created(),
        headers={"X-Max-Bot-Api-Secret": "s3cret-max"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert scheduled and scheduled[0][0] == max_bot.id


async def test_webhook_inactive_bot_404(client, db, max_bot):
    max_bot.is_active = False
    await db.commit()
    resp = await client.post(
        f"/webhook/max/{max_bot.id}",
        json=_message_created(),
        headers={"X-Max-Bot-Api-Secret": "s3cret-max"},
    )
    assert resp.status_code == 404


# --- Общий путь обработки -----------------------------------------------------


@pytest.fixture
def fake_ai(monkeypatch):
    async def _fake_run_ai(db, dialog, client_message):
        run = AIRun(
            dialog_id=dialog.id, input_message_id=client_message.id,
            provider="test", model="test",
        )
        db.add(run)
        reply = Message(dialog_id=dialog.id, role=MessageRole.ai, text="Да, есть!")
        db.add(reply)
        await db.commit()
        run.output_message_id = reply.id
        output = AgentOutput(reply_text="Да, есть!", confidence_score=0.95)
        return output, run, [ReplyPart(text=reply.text, image_urls=[], message=reply)]

    monkeypatch.setattr("app.ai.runner.run_ai", _fake_run_ai)


@pytest.fixture
async def greeting_script(db, max_bot):
    """Приветствие берётся из того же скрипта, что и в ВК."""
    db.add(Script(
        type_id=max_bot.dialog_type_id,
        condition="первое приветственное сообщение",
        phrase_text="Здравствуйте! Меня зовут София 🙂",
        is_active=True,
        funnel_stage="greeting",
    ))
    await db.commit()


@pytest.fixture
def fake_sender(monkeypatch):
    sent = []

    async def _fake_send(db, dialog, text):
        sent.append((dialog.id, text))
        return MaxSentMessage(message_id=f"out-{len(sent)}")

    monkeypatch.setattr("app.messaging.send_to_dialog", _fake_send)
    return sent


async def test_message_created_goes_through_common_pipeline(
    db, max_bot, fake_ai, fake_sender,
):
    """Диалог из MAX проходит тот же путь, что и диалог из ВК."""
    msg = parse_message_created(_message_created())
    await handle_message_new(db, max_bot, msg)

    client = await db.scalar(select(Client).where(Client.vk_user_id == 555))
    assert client.vk_group_id == max_bot.id
    assert client.source == "max:777001"
    # Имя MAX присылает в событии — в профиль ходить не за чем.
    assert (client.name, client.last_name) == ("Анастасия", "Петрова")

    dialog = await db.scalar(select(Dialog).where(Dialog.client_id == client.id))
    assert dialog.type_id == max_bot.dialog_type_id
    # Переписки до подключения у бота не бывает — ИИ берёт диалог сразу.
    assert dialog.prior_history is False
    assert dialog.ai_paused is False
    assert fake_sender == [(dialog.id, "Да, есть!")]


async def test_duplicate_mid_is_skipped(db, max_bot, fake_ai, fake_sender):
    msg = parse_message_created(_message_created())
    await handle_message_new(db, max_bot, msg)
    await handle_message_new(db, max_bot, parse_message_created(_message_created()))
    assert len(fake_sender) == 1


async def test_manager_message_from_max_pauses_dialog_before_client_replies(db, max_bot):
    """Ручной ответ от имени бота заводит паузу ещё до первого текста клиента."""
    handled = await handle_bot_message(db, max_bot, _bot_message_created())

    assert handled is True
    client = await db.scalar(select(Client).where(Client.vk_user_id == 555))
    dialog = await db.scalar(select(Dialog).where(Dialog.client_id == client.id))
    assert dialog.ai_paused is True
    manager_msg = await db.scalar(select(Message).where(Message.role == MessageRole.curator))
    assert manager_msg.text == "Макет готов"


async def test_first_max_message_checks_history_for_manual_reply(
    db, max_bot, fake_ai, fake_sender, monkeypatch,
):
    """Проверяем историю, если исходящее менеджера пришло раньше нашего вебхука."""
    outgoing = _bot_message_created()["message"]

    async def _history(*_args, **_kwargs):
        return [outgoing]

    monkeypatch.setattr("app.max.client.get_messages", _history)
    payload = _message_created()
    msg = parse_message_created(payload)

    assert await pause_if_first_message_has_manager_reply(db, max_bot, payload, msg) is True
    await handle_message_new(db, max_bot, msg)

    dialog = (await db.execute(select(Dialog))).scalars().one()
    assert dialog.ai_paused is True
    assert fake_sender == []


# --- «Начать»: bot_started и «/start» ------------------------------------------


def test_start_command_recognised_with_deeplink():
    """«/start sweetgold» — это нажатая кнопка, а не вопрос клиента."""
    start = start_command(_message_created(text="/start sweetgold"))
    assert start == {
        "user_id": 555, "ref": "sweetgold",
        "first_name": "Анастасия", "last_name": "Петрова",
    }


def test_bare_start_command_has_no_tag():
    assert start_command(_message_created(text="/start"))["ref"] is None


def test_ordinary_message_is_not_a_start_command():
    assert start_command(_message_created()) is None
    assert start_command(_message_created(text="/startup хочу заказать")) is None


async def test_bot_started_tags_client_by_deeplink(db, max_bot):
    await handle_start(
        db, max_bot, 606, ref="sweetgold", first_name="Ирина", last_name="К.",
    )
    client = await db.scalar(select(Client).where(Client.vk_user_id == 606))
    assert client.marketing_tags == ["sweetgold"]
    assert client.name == "Ирина"
    # Диалог заводим сразу: в MAX первым говорит бот.
    assert await db.scalar(select(Dialog).where(Dialog.client_id == client.id)) is not None


async def test_start_greets_first(db, max_bot, fake_sender, greeting_script):
    """Человек нажал «Начать» — бот здоровается сам, не дожидаясь сообщения."""
    await handle_start(db, max_bot, 606, first_name="Ирина")

    client = await db.scalar(select(Client).where(Client.vk_user_id == 606))
    dialog = await db.scalar(select(Dialog).where(Dialog.client_id == client.id))
    assert fake_sender == [(dialog.id, "Здравствуйте! Меня зовут София 🙂")]
    saved = (await db.execute(
        select(Message).where(Message.dialog_id == dialog.id)
    )).scalars().all()
    # Команда «/start» в переписку не попадает — клиент её не писал.
    assert [m.role for m in saved] == [MessageRole.ai]


async def test_start_greets_only_once(db, max_bot, fake_sender, greeting_script):
    """MAX может прислать и bot_started, и «/start» — здороваемся один раз."""
    await handle_start(db, max_bot, 606)
    await handle_start(db, max_bot, 606)
    assert len(fake_sender) == 1


async def test_start_command_message_routes_to_greeting(
    client, db, max_bot, fake_sender, greeting_script, monkeypatch,
):
    """«/start» из вебхука доходит до приветствия, а не до модели."""
    from app.max import webhook as max_webhook

    max_bot.is_active = True
    await db.commit()

    monkeypatch.setattr(
        "app.db.session.AsyncSessionLocal",
        lambda: _FakeSessionCtx(db),
    )
    await max_webhook.process_event(max_bot.id, _message_created(text="/start sweetgold"))

    saved_client = await db.scalar(select(Client).where(Client.vk_user_id == 555))
    assert saved_client.marketing_tags == ["sweetgold"]
    assert len(fake_sender) == 1


class _FakeSessionCtx:
    """process_event открывает свою сессию — в тестах отдаём ту же самую."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


async def _dialog_of(db, user_id=555):
    client = await db.scalar(select(Client).where(Client.vk_user_id == user_id))
    dialog = await db.scalar(select(Dialog).where(Dialog.client_id == client.id))
    await db.refresh(dialog)
    return dialog


async def test_bot_stopped_stops_pings_but_does_not_forbid_sending(
    db, max_bot, fake_ai, fake_sender,
):
    """Стоп-бот гасит воронку; запрет отправки ставит только отказ самого MAX.

    Событием отметку не ставим: 27.08 так «в блоке» оказались 162 MAX-диалога
    из 361, притом что клиентам всё это время писали.
    """
    await handle_message_new(db, max_bot, parse_message_created(_message_created()))
    dialog = await _dialog_of(db)
    db.add(DialogPingState(dialog_id=dialog.id, funnel_type="knows_price", current_step=1))
    await db.commit()

    await handle_bot_stopped(db, max_bot, {
        "update_type": "bot_stopped", "chat_id": 900, "user_id": 555,
    })

    dialog = await _dialog_of(db)
    assert dialog.vk_blocked is False
    state = await db.scalar(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
    )
    assert state.is_completed is True


async def test_dialog_removed_changes_nothing(db, max_bot, fake_ai, fake_sender):
    """Удалённая переписка возвращается от первого же сообщения бота."""
    await handle_message_new(db, max_bot, parse_message_created(_message_created()))
    dialog = await _dialog_of(db)
    db.add(DialogPingState(dialog_id=dialog.id, funnel_type="knows_price", current_step=1))
    await db.commit()

    await handle_dialog_removed(db, max_bot, {
        "update_type": "dialog_removed", "chat_id": 900, "user_id": 555,
    })

    dialog = await _dialog_of(db)
    assert dialog.vk_blocked is False
    state = await db.scalar(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
    )
    assert state.is_completed is False


async def test_incoming_message_clears_stale_block(db, max_bot, fake_ai, fake_sender):
    """Клиент пишет — значит канал живой, старая отметка снимается."""
    await handle_message_new(db, max_bot, parse_message_created(_message_created()))
    dialog = await _dialog_of(db)
    dialog.vk_blocked = True
    await db.commit()

    await handle_message_new(
        db, max_bot, parse_message_created(_message_created(mid="mid-2", text="Ещё вопрос")),
    )

    dialog = await _dialog_of(db)
    assert dialog.vk_blocked is False


async def test_start_again_clears_stale_block(db, max_bot, fake_sender, greeting_script):
    """Клиент вернулся по кнопке «Начать» — писать ему можно."""
    await handle_start(db, max_bot, 555)
    dialog = await _dialog_of(db)
    dialog.vk_blocked = True
    await db.commit()

    await handle_start(db, max_bot, 555)

    dialog = await _dialog_of(db)
    assert dialog.vk_blocked is False


async def test_clear_max_blocks_command_clears_only_max(db, max_bot, fake_ai, fake_sender):
    """Разовая уборка накопленных отметок: ВК она не трогает."""
    from app.commands.clear_max_blocks import run

    await handle_message_new(db, max_bot, parse_message_created(_message_created()))
    max_dialog = await _dialog_of(db)
    max_dialog.vk_blocked = True

    vk_group = VkGroup(
        platform="vk", group_id=44440184, name="Hemilton MAIN", access_token="t",
        dialog_type_id=max_bot.dialog_type_id,
    )
    db.add(vk_group)
    await db.flush()
    vk_client = Client(vk_user_id=999, vk_group_id=vk_group.id, name="Пётр")
    db.add(vk_client)
    await db.flush()
    vk_dialog = Dialog(client_id=vk_client.id, type_id=max_bot.dialog_type_id, vk_blocked=True)
    db.add(vk_dialog)
    await db.commit()

    import app.commands.clear_max_blocks as command
    command.AsyncSessionLocal = lambda: _FakeSessionCtx(db)
    try:
        assert await run(apply=True) == 1
    finally:
        importlib.reload(command)

    await db.refresh(max_dialog)
    await db.refresh(vk_dialog)
    assert max_dialog.vk_blocked is False
    assert vk_dialog.vk_blocked is True
