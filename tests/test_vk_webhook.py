"""VK Callback API: confirmation, secret, message_new (дедуп), message_reply (пауза ИИ)."""
import pytest
from sqlalchemy import func, select

from app.ai.schemas import AgentOutput
from app.db.models import AIRun, Client, Dialog, DialogType, Message, MessageRole, VkGroup
from app.vk.webhook import (
    handle_message_new,
    handle_message_reply,
    parse_message_event,
)


@pytest.fixture
async def vk_group(db):
    dt = DialogType(name="clothes", display_name="Одежда")
    db.add(dt)
    await db.flush()
    group = VkGroup(
        group_id=111222,
        name="Магазин одежды",
        access_token="vk1.a.test-token",
        confirmation_code="confirm123",
        secret_key="s3cret",
        dialog_type_id=dt.id,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


def _event(event_type="message_new", *, group_id=111222, secret="s3cret",
           from_id=555, text="Здравствуйте, есть размер M?", message_id=42,
           random_id=0, attachments=None):
    return {
        "type": event_type,
        "group_id": group_id,
        "secret": secret,
        "object": {
            "message": {
                "id": message_id,
                "from_id": from_id,
                "peer_id": from_id,
                "text": text,
                "random_id": random_id,
                "attachments": attachments or [],
            }
        },
    }


# --- Эндпоинт -----------------------------------------------------------------


async def test_confirmation_returns_code(client, vk_group):
    resp = await client.post("/webhook/vk", json={"type": "confirmation", "group_id": 111222})
    assert resp.status_code == 200
    assert resp.text == "confirm123"


async def test_unknown_group_404(client, db):
    resp = await client.post("/webhook/vk", json={"type": "confirmation", "group_id": 999})
    assert resp.status_code == 404


async def test_bad_secret_403(client, vk_group):
    resp = await client.post("/webhook/vk", json=_event(secret="wrong"))
    assert resp.status_code == 403


async def test_message_new_acks_and_schedules(client, vk_group, monkeypatch):
    scheduled = []
    monkeypatch.setattr("app.api.vk.schedule_event", lambda pk, payload: scheduled.append((pk, payload)))
    resp = await client.post("/webhook/vk", json=_event())
    assert resp.status_code == 200
    assert resp.text == "ok"
    assert len(scheduled) == 1
    assert scheduled[0][0] == vk_group.id


# --- Обработчики --------------------------------------------------------------


@pytest.fixture
def fake_ai(monkeypatch):
    """run_ai создаёт реальный AIRun (нужен дедупу) и возвращает готовый ответ."""
    calls = []

    async def _fake_run_ai(db, dialog, client_message):
        calls.append(client_message.id)
        run = AIRun(
            dialog_id=dialog.id,
            input_message_id=client_message.id,
            provider="test",
            model="test",
        )
        db.add(run)
        await db.commit()
        output = AgentOutput(reply_text="Да, есть в наличии!", confidence_score=0.95)
        return output, run, [], "Да, есть в наличии!"

    monkeypatch.setattr("app.ai.runner.run_ai", _fake_run_ai)
    return calls


@pytest.fixture
def fake_sender(monkeypatch):
    sent = []

    async def _fake_send(db, dialog, text):
        sent.append((dialog.id, text))
        return 777

    monkeypatch.setattr("app.vk.sender.send_to_dialog", _fake_send)
    return sent


async def test_message_new_creates_entities_and_sends(db, vk_group, fake_ai, fake_sender):
    msg = parse_message_event(_event())
    await handle_message_new(db, vk_group, msg)

    client = await db.scalar(select(Client).where(Client.vk_user_id == 555))
    assert client is not None
    assert client.vk_group_id == vk_group.id

    dialog = await db.scalar(select(Dialog).where(Dialog.client_id == client.id))
    assert dialog is not None
    assert dialog.type_id == vk_group.dialog_type_id

    messages = (await db.execute(
        select(Message).where(Message.dialog_id == dialog.id).order_by(Message.id)
    )).scalars().all()
    assert messages[0].role == MessageRole.client
    assert messages[0].external_message_id == "42"

    assert fake_ai == [messages[0].id]
    assert fake_sender == [(dialog.id, "Да, есть в наличии!")]


async def test_message_new_dedup_skips_retry(db, vk_group, fake_ai, fake_sender):
    msg = parse_message_event(_event())
    await handle_message_new(db, vk_group, msg)
    # ВК ретраит то же событие — второй прогон не должен породить второй AIRun.
    await handle_message_new(db, vk_group, parse_message_event(_event()))

    assert len(fake_ai) == 1
    n_client_msgs = await db.scalar(
        select(func.count()).select_from(Message).where(Message.role == MessageRole.client)
    )
    assert n_client_msgs == 1


async def test_message_new_ai_paused_saves_but_no_ai(db, vk_group, fake_ai, fake_sender):
    first = parse_message_event(_event())
    await handle_message_new(db, vk_group, first)
    dialog = (await db.execute(select(Dialog))).scalars().first()
    dialog.ai_paused = True
    await db.commit()

    second = parse_message_event(_event(message_id=43, text="А доставка есть?"))
    await handle_message_new(db, vk_group, second)

    assert len(fake_ai) == 1  # второй ран не запускался
    n_client_msgs = await db.scalar(
        select(func.count()).select_from(Message).where(Message.role == MessageRole.client)
    )
    assert n_client_msgs == 2  # но сообщение сохранено


async def test_message_reply_operator_pauses_ai(db, vk_group, fake_ai, fake_sender):
    # Клиент написал — диалог существует.
    await handle_message_new(db, vk_group, parse_message_event(_event()))
    # Живой оператор ответил из интерфейса ВК: random_id=0.
    reply = parse_message_event(_event(
        "message_reply", from_id=-111222, text="Оператор на связи", message_id=99, random_id=0,
    ))
    reply.peer_id = 555
    await handle_message_reply(db, vk_group, reply)

    dialog = (await db.execute(select(Dialog))).scalars().first()
    assert dialog.ai_paused is True
    curator_msg = await db.scalar(select(Message).where(Message.role == MessageRole.curator))
    assert curator_msg is not None
    assert curator_msg.text == "Оператор на связи"


async def test_message_reply_own_api_send_ignored(db, vk_group, fake_ai, fake_sender):
    await handle_message_new(db, vk_group, parse_message_event(_event()))
    # Эхо нашей же отправки через messages.send: random_id != 0.
    reply = parse_message_event(_event(
        "message_reply", from_id=-111222, text="Да, есть в наличии!", message_id=100,
        random_id=123456,
    ))
    await handle_message_reply(db, vk_group, reply)

    dialog = (await db.execute(select(Dialog))).scalars().first()
    assert dialog.ai_paused is False
    n_curator = await db.scalar(
        select(func.count()).select_from(Message).where(Message.role == MessageRole.curator)
    )
    assert n_curator == 0


# --- Парсинг ------------------------------------------------------------------


def test_parse_message_event_photo_attachment():
    event = _event(text="", attachments=[{
        "type": "photo",
        "photo": {"sizes": [
            {"width": 100, "height": 100, "url": "http://img/small.jpg"},
            {"width": 800, "height": 600, "url": "http://img/big.jpg"},
        ]},
    }])
    msg = parse_message_event(event)
    assert msg.files == ["http://img/big.jpg"]
    assert msg.text == "[фото]"


def test_parse_message_event_empty_returns_none():
    assert parse_message_event(_event(text="")) is None
