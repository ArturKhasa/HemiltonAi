"""Пинги клиенту, который нам не написал ни строчки.

В ВК диалог заводит либо сообщение клиента, либо рассылка, поэтому discovery
всегда требовал хотя бы одно входящее: пинговать второе — писать незнакомому
человеку. В MAX это правило отрезало живых лидов. Там боту пишут только после
кнопки «Начать»: клиент её нажал, получил приветствие, вопрос про надпись и —
через 15 минут молчания — цену с вопросом про доставку, не написав ни слова. На
этом всё и заканчивалось: 24 диалога MAX без единой пинг-воронки (ОП, 27.08:
«в максе нет пингов по клиентам после вопроса о доставке, их нужно подключить»).
"""
from datetime import timedelta

import pytest

from app.db.models import Client, Dialog, DialogType, Message, MessageRole, VkGroup
from app.ping import worker
from app.utils.time import msk_now

# Полдень: discovery работает с 8 до 22, и тест не должен зависеть от часа прогона.
NOON = msk_now().replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.fixture
async def dialog_type(db):
    dt = DialogType(name="clothes", display_name="Одежда")
    db.add(dt)
    await db.flush()
    return dt


@pytest.fixture
def frozen_noon(monkeypatch):
    monkeypatch.setattr("app.ping.worker.msk_now", lambda: NOON)


@pytest.fixture
def same_session(db, monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    # worker импортирует фабрику сессий по имени — подменять надо у него.
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: _Ctx())


@pytest.fixture
def discovered(monkeypatch):
    """Кого discovery отдал на заведение воронки — саму воронку не строим."""
    picked = []

    async def _init(db, dialog, last_ai_at, now):
        picked.append(dialog.id)

    monkeypatch.setattr(worker, "_init_ping_state", _init)
    return picked


async def _dialog(db, dialog_type, *, platform, group_id, user_id, client_wrote):
    group = VkGroup(
        platform=platform, group_id=group_id, name="Хэмилтон",
        access_token="t", is_active=True, dialog_type_id=dialog_type.id,
    )
    db.add(group)
    await db.flush()
    client = Client(vk_user_id=user_id, vk_group_id=group.id, name="Али")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, type_id=dialog_type.id)
    db.add(dialog)
    await db.flush()

    if client_wrote:
        db.add(Message(
            dialog_id=dialog.id, role=MessageRole.client, text="Цена?",
            created_at=NOON - timedelta(hours=3),
        ))
    # Последним словом — наше: приветствие и догоняющая цена с вопросом о доставке.
    db.add(Message(
        dialog_id=dialog.id, role=MessageRole.ai,
        text="Стоимость толстовки 5 990 ₽. В какой город нужна будет доставка?",
        created_at=NOON - timedelta(hours=2),
    ))
    dialog.last_message_at = NOON - timedelta(hours=2)
    await db.commit()
    return dialog


async def test_silent_max_client_gets_a_ping_funnel(
    db, dialog_type, frozen_noon, same_session, discovered,
):
    """Кнопку «Начать» он нажал — это и есть согласие на разговор."""
    dialog = await _dialog(
        db, dialog_type, platform="max", group_id=777001, user_id=555, client_wrote=False,
    )

    await worker.discover()

    assert discovered == [dialog.id]


async def test_silent_vk_client_is_still_skipped(
    db, dialog_type, frozen_noon, same_session, discovered,
):
    """В ВК молчание означает, что диалог завела рассылка, а не клиент."""
    await _dialog(
        db, dialog_type, platform="vk", group_id=44440184, user_id=556, client_wrote=False,
    )

    await worker.discover()

    assert discovered == []


async def test_vk_client_who_wrote_is_discovered(
    db, dialog_type, frozen_noon, same_session, discovered,
):
    """Обычный путь ВК не изменился."""
    dialog = await _dialog(
        db, dialog_type, platform="vk", group_id=44440184, user_id=557, client_wrote=True,
    )

    await worker.discover()

    assert discovered == [dialog.id]


async def test_paused_max_dialog_is_left_alone(
    db, dialog_type, frozen_noon, same_session, discovered,
):
    """Диалог, который ведёт человек, пингов не получает и в MAX."""
    dialog = await _dialog(
        db, dialog_type, platform="max", group_id=777002, user_id=558, client_wrote=False,
    )
    dialog.ai_paused = True
    await db.commit()

    await worker.discover()

    assert discovered == []
