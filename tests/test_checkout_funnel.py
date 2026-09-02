"""Свои воронки пингов для горячих ступеней.

Лена, 01.09: «Нужно сделать новую воронку пингов для лидов, которые молчат после
способов оплаты, сами пинги добавлю сама».

До этого таких пингов не было ни одного, и завести их в панели было нельзя: на
проде заведена одна воронка `knows_price`, а лид, дошедший до способов оплаты,
из пингов вообще исключался заслоном горячей стадии. Воронка `after_payment`
(счёт выставлен, предоплаты нет) в коде вызывалась с 27.08, но правил под неё в
базе не было — вызов молча выходил по «no rules».

Назначает такую воронку код по факту, а не классификатор по переписке: момент
«клиент увидел способы оплаты» лестница статусов и так считает по доставленным
сообщениям.
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import (
    Client, Dialog, DialogPingState, DialogStatusConfig, DialogType, Message,
    MessageRole, PingRule, VkGroup,
)
from app.ping import worker
from app.sales.status_flow import sync_status
from app.sales.status_names import AWAITING_PREPAY, HOT, LADDER
from app.utils.time import msk_now

PRICE = "Стоимость толстовки со скидкой СЕГОДНЯ - 5 990 ₽"
CHECKOUT = "Получается сумма заказа - 5 990 ₽\n\nА по оплате у нас есть 2 варианта:"
INVOICE = "Вот ссылка на предоплату: https://hemilton.ru/payment/12"


@pytest.fixture
async def dialog_type(db):
    dt = DialogType(name="hemilton", display_name="Hemilton")
    db.add(dt)
    await db.flush()
    return dt


@pytest.fixture
async def statuses(db):
    for order, name in enumerate(LADDER, start=1):
        db.add(DialogStatusConfig(name=name, pattern="", is_active=True, sort_order=order * 10))
    await db.commit()


@pytest.fixture
async def rules(db, dialog_type):
    for funnel, step, delay in (
        ("knows_price", 1, 900),
        ("checkout", 1, 1800),
        ("checkout", 2, 10800),
        ("after_payment", 1, 3600),
    ):
        db.add(PingRule(
            type_id=dialog_type.id, funnel_type=funnel, step=step,
            delay_seconds=delay, phrase_text=f"{funnel} {step}", is_active=True,
        ))
    await db.commit()


@pytest.fixture
async def dialog(db, dialog_type):
    group = VkGroup(platform="vk", group_id=44440184, name="Hemilton",
                    access_token="t", is_active=True)
    db.add(group)
    await db.flush()
    client = Client(vk_user_id=189680451, vk_group_id=group.id, name="Иван")
    db.add(client)
    await db.flush()
    d = Dialog(client_id=client.id, type_id=dialog_type.id)
    db.add(d)
    await db.flush()
    await db.commit()
    return d


@pytest.fixture(autouse=True)
def no_telegram(monkeypatch):
    async def _fake(text, what, dialog_id):
        return None

    monkeypatch.setattr("app.notify._send", _fake)
    monkeypatch.setattr("app.notify.notifications_configured", lambda: False)


async def _say(db, dialog, role, text):
    db.add(Message(dialog_id=dialog.id, role=role, text=text))
    await db.commit()


class TestFunnelPerRung:
    async def test_payment_options_start_the_checkout_funnel(
        self, db, dialog, statuses, rules,
    ):
        await _say(db, dialog, MessageRole.ai, CHECKOUT)

        assert await sync_status(db, dialog) == HOT

        state = await db.scalar(select(DialogPingState))
        assert state.funnel_type == "checkout"
        assert state.current_step == 1

    async def test_invoice_starts_the_after_payment_funnel(self, db, dialog, statuses, rules):
        await _say(db, dialog, MessageRole.ai, INVOICE)

        assert await sync_status(db, dialog) == AWAITING_PREPAY

        state = await db.scalar(select(DialogPingState))
        assert state.funnel_type == "after_payment"

    async def test_ordinary_price_keeps_the_general_funnel(self, db, dialog, statuses, rules):
        """Расчёт — это ещё не горячая ступень: воронку выбирает discovery."""
        await _say(db, dialog, MessageRole.ai, PRICE)

        await sync_status(db, dialog)

        assert await db.scalar(select(DialogPingState)) is None

    async def test_dialog_taken_by_a_human_gets_no_funnel(self, db, dialog, statuses, rules):
        """Способы оплаты отправил менеджер — писать поверх живого разговора нельзя."""
        dialog.ai_paused = True
        # Реплики менеджера лестница читает только там, где клиент заговорил:
        # иначе шагом воронки стала бы каждая рассылка.
        await _say(db, dialog, MessageRole.client, "Беру")
        await _say(db, dialog, MessageRole.curator, CHECKOUT)

        assert await sync_status(db, dialog) == HOT

        assert await db.scalar(select(DialogPingState)) is None


class TestHotStageGate:
    async def test_named_funnel_survives_the_hot_stage_gate(
        self, db, dialog, statuses, rules, monkeypatch,
    ):
        """Заслон написан против ОБЩЕЙ воронки. Именная — это и есть тот самый
        индивидуальный дожим, ради которого заслон ставили."""
        reached = []

        async def _run(db_, state_, dialog_):
            reached.append(state_.funnel_type)
            raise AssertionError("дошли до агента")

        monkeypatch.setattr("app.ping.agent.run_ping_agent", _run)
        dialog.funnel_stage = "checkout"
        await _say(db, dialog, MessageRole.ai, CHECKOUT)
        now = msk_now()
        state = DialogPingState(
            dialog_id=dialog.id, funnel_type="checkout", current_step=1,
            next_ping_due_at=now - timedelta(minutes=1),
        )
        db.add(state)
        await db.commit()

        with pytest.raises(AssertionError, match="дошли до агента"):
            await worker._process_state(db, state, now)

        assert reached == ["checkout"]
        assert dialog.ai_paused is False


class TestAutoDetectionIgnoresNamedFunnels:
    async def test_classifier_never_picks_a_forced_funnel(self, db, dialog, rules, monkeypatch):
        """Иначе на каждый молчащий диалог уходил бы лишний запрос к модели со
        списком воронок, про которые в промпте классификатора не сказано ничего."""
        from app.ping.agent import detect_funnel_with_ai

        async def _no_model(*args, **kwargs):
            raise AssertionError("классификатор не должен вызываться: воронка одна")

        monkeypatch.setattr("agents.Runner.run", _no_model)
        await _say(db, dialog, MessageRole.ai, PRICE)

        funnel, reason = await detect_funnel_with_ai(db, dialog)

        assert funnel == "knows_price"
