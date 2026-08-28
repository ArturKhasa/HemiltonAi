"""Ответ живого менеджера клиенту из панели.

Раньше написать в боевой диалог было неоткуда: единственный эндпоинт отправки
требовал `dialog.is_test` и отдавал 403 на всё остальное, а в интерфейсе стояла
надпись «Реальный диалог — только просмотр». Диалог с меткой «Нужен куратор»
менеджер видел, а сделать с ним ничего не мог — и уходил писать в ВК, откуда мы
его сообщений не видели.

Замечание ОП от 10 августа, 13:49: «Здесь с макетом подключался уже менеджер в
работу, потом снова включилась ии. Надо бы ей отключаться, если менеджер уже
начал общение, чтобы не перебивать».
"""
import pytest
from sqlalchemy import select

from app.auth.service import hash_password
from app.db.models import (
    Client, Dialog, DialogPingState, DialogType, Message, MessageRole, User, UserRole,
)
from app.utils.time import msk_now
from app.vk.sender import SentMessage


@pytest.fixture
async def curator_headers(client, db):
    """Админ: направления ему выданы все, а роль для эндпоинта та же."""
    db.add(User(email="boss@test.io", password_hash=hash_password("pass1234"), role=UserRole.admin))
    await db.commit()
    resp = await client.post("/api/auth/login", json={"email": "boss@test.io", "password": "pass1234"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def live_dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    c = Client(vk_user_id=555)
    db.add(c)
    await db.flush()
    d = Dialog(client_id=c.id, type_id=1, is_test=False)
    db.add(d)
    await db.flush()
    db.add(DialogPingState(
        dialog_id=d.id, funnel_type="knows_price", current_step=2,
        next_ping_due_at=msk_now(),
    ))
    await db.commit()
    return d


@pytest.fixture
def fake_send(monkeypatch):
    sent = []

    async def _send(db, dialog, text):
        sent.append((dialog.id, text))
        return SentMessage(message_id=161450, random_ids=[424242])

    monkeypatch.setattr("app.messaging.send_to_dialog", _send)
    return sent


async def test_manager_reply_reaches_the_client(client, db, curator_headers, live_dialog, fake_send):
    resp = await client.post(
        f"/api/chat/{live_dialog.id}/reply",
        headers=curator_headers,
        json={"text": "Макет уже у дизайнера, пришлю сегодня"},
    )

    assert resp.status_code == 200
    assert resp.json()["role"] == "curator"
    assert fake_send == [(live_dialog.id, "Макет уже у дизайнера, пришлю сегодня")]

    msg = await db.scalar(select(Message).where(Message.role == MessageRole.curator))
    assert msg.external_message_id == "161450"
    assert msg.msg_metadata["vk_random_ids"] == [424242]


async def test_manager_reply_takes_the_dialog_from_ai(client, db, curator_headers, live_dialog, fake_send):
    """Пока менеджер ведёт диалог, ИИ молчит и пинги не идут."""
    await client.post(
        f"/api/chat/{live_dialog.id}/reply",
        headers=curator_headers,
        json={"text": "Здравствуйте, я подключилась"},
    )

    await db.refresh(live_dialog)
    assert live_dialog.ai_paused is True
    state = await db.scalar(
        select(DialogPingState).where(DialogPingState.dialog_id == live_dialog.id)
    )
    assert state.is_completed is True


async def test_resuming_ai_removes_the_stopped_ping_state(
    client, db, curator_headers, live_dialog, fake_send,
):
    await client.post(
        f"/api/chat/{live_dialog.id}/reply",
        headers=curator_headers,
        json={"text": "Здравствуйте, я подключилась"},
    )

    resp = await client.post(
        f"/api/dialogs/{live_dialog.id}/ai-pause",
        headers=curator_headers,
        json={"paused": False},
    )

    assert resp.status_code == 200
    await db.refresh(live_dialog)
    assert live_dialog.ai_paused is False
    state = await db.scalar(
        select(DialogPingState).where(DialogPingState.dialog_id == live_dialog.id)
    )
    assert state is None


async def test_empty_reply_rejected(client, curator_headers, live_dialog, fake_send):
    resp = await client.post(
        f"/api/chat/{live_dialog.id}/reply", headers=curator_headers, json={"text": "   "},
    )
    assert resp.status_code == 400
    assert fake_send == []


async def test_failed_send_does_not_leave_a_phantom_message(
    client, db, curator_headers, live_dialog, monkeypatch,
):
    """Отправка упала — текст помечается недоставленным и в историю не идёт."""
    async def _boom(db_, dialog, text):
        raise RuntimeError("VK недоступен")

    monkeypatch.setattr("app.messaging.send_to_dialog", _boom)

    resp = await client.post(
        f"/api/chat/{live_dialog.id}/reply", headers=curator_headers, json={"text": "Проверка"},
    )

    assert resp.status_code == 502
    msg = await db.scalar(select(Message).where(Message.role == MessageRole.curator))
    assert msg.msg_metadata["delivery_failed"] is True
