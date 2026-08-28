"""Пинги клиенту, который нам не написал ни строчки.

В ВК диалог заводит либо сообщение клиента, либо рассылка, поэтому discovery
всегда требовал хотя бы одно входящее: пинговать второе — писать незнакомому
человеку. В MAX это правило отрезало живых лидов. Там боту пишут только после
кнопки «Начать»: клиент её нажал, получил приветствие, вопрос про надпись и —
через 20 минут молчания — цену с вопросом про доставку, не написав ни слова. На
этом всё и заканчивалось: 24 диалога MAX без единой пинг-воронки (ОП, 27.08:
«в максе нет пингов по клиентам после вопроса о доставке, их нужно подключить»).
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import (
    Client, Dialog, DialogPingState, DialogType, Message, MessageRole, PingRule, VkGroup,
)
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

    async def _init(db, dialog, last_outbound_at, now, *, restart_completed=False):
        picked.append((dialog.id, restart_completed))

    monkeypatch.setattr(worker, "_init_ping_state", _init)
    return picked


async def _dialog(
    db, dialog_type, *, platform, group_id, user_id, client_wrote,
    last_role=MessageRole.ai, last_metadata=None,
):
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
        dialog_id=dialog.id, role=last_role,
        text="Стоимость толстовки 5 990 ₽. В какой город нужна будет доставка?",
        created_at=NOON - timedelta(hours=2),
        msg_metadata=last_metadata,
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

    assert discovered == [(dialog.id, False)]


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

    assert discovered == [(dialog.id, False)]


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


async def test_resumed_dialog_after_manager_reply_is_discovered(
    db, dialog_type, frozen_noon, same_session, discovered,
):
    """Снятая пауза передаёт менеджерский диалог обратно пингам."""
    dialog = await _dialog(
        db,
        dialog_type,
        platform="max",
        group_id=777003,
        user_id=559,
        client_wrote=True,
        last_role=MessageRole.curator,
        last_metadata={"max_operator": True},
    )
    db.add(DialogPingState(
        dialog_id=dialog.id,
        funnel_type="knows_price",
        current_step=2,
        is_completed=True,
    ))
    await db.commit()

    await worker.discover()

    assert discovered == [(dialog.id, True)]


async def test_broadcast_is_not_discovered_as_a_manager_hand_back(
    db, dialog_type, frozen_noon, same_session, discovered,
):
    await _dialog(
        db,
        dialog_type,
        platform="vk",
        group_id=44440185,
        user_id=560,
        client_wrote=True,
        last_role=MessageRole.curator,
        last_metadata={"broadcast": True},
    )

    await worker.discover()

    assert discovered == []


async def test_failed_manager_message_is_not_discovered(
    db, dialog_type, frozen_noon, same_session, discovered,
):
    await _dialog(
        db,
        dialog_type,
        platform="vk",
        group_id=44440186,
        user_id=562,
        client_wrote=True,
        last_role=MessageRole.curator,
        last_metadata={"delivery_failed": True},
    )

    await worker.discover()

    assert discovered == []


async def test_restarting_replaces_the_completed_state(db, dialog_type, monkeypatch):
    """Историческая ручная передача не упирается в unique(dialog_id)."""
    dialog = await _dialog(
        db,
        dialog_type,
        platform="max",
        group_id=777004,
        user_id=561,
        client_wrote=True,
        last_role=MessageRole.curator,
        last_metadata={"max_operator": True},
    )
    db.add_all([
        PingRule(
            type_id=dialog_type.id,
            funnel_type="knows_price",
            step=1,
            delay_seconds=900,
            manual_text="Пинг",
        ),
        DialogPingState(
            dialog_id=dialog.id,
            funnel_type="knows_price",
            current_step=2,
            is_completed=True,
        ),
    ])
    await db.commit()

    async def _funnel(db_, dialog_):
        return "knows_price", "цена уже отправлена"

    monkeypatch.setattr("app.ping.agent.detect_funnel_with_ai", _funnel)
    await worker._init_ping_state(
        db,
        dialog,
        NOON - timedelta(hours=2),
        NOON,
        restart_completed=True,
    )
    await db.commit()

    states = list((await db.execute(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
    )).scalars().all())
    assert len(states) == 1
    assert states[0].is_completed is False
    assert states[0].current_step == 1
