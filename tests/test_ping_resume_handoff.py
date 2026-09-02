"""Менеджер снял паузу — пинги продолжаются с того шага, где встали.

Лена, 01.09: «Если менеджер снимает ИИ с паузы - ИИ нужно продолжить пинговать
лида вне зависимости от статуса/прошлого диалога», и уточнение: «на чем
закончили, то нужно и продолжить. Например, лид заигнорил после выбора цвета.
Менеджер включил ИИ и она пингует клиента, подстраиваясь под последнее сообщение
менеджера».

Правка от 28.08 удаляла завершённую воронку и ждала discovery. Этого мало:
discovery смотрит только сутки назад, а диалог менеджеру отдают и на неделю, и
новую воронку он заводит с ПЕРВОГО шага — клиент, до которого дошли двенадцать,
получил бы «Я Вам стоимость отправила, а вы мне что-то не отвечаете))» заново.
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import (
    Client, Dialog, DialogPingState, DialogType, Message, MessageRole, PingRule, VkGroup,
)
from app.ping import worker
from app.utils.time import msk_now

NOW = msk_now().replace(hour=12, minute=0, second=0, microsecond=0)

# Задержки как в проде: 15 минут, час, два часа.
STEPS = ((1, 900), (2, 3600), (4, 7200))


@pytest.fixture
async def dialog_type(db):
    dt = DialogType(name="hemilton", display_name="Hemilton")
    db.add(dt)
    await db.flush()
    return dt


@pytest.fixture
async def rules(db, dialog_type):
    for step, delay in STEPS:
        db.add(PingRule(
            type_id=dialog_type.id, funnel_type="knows_price", step=step,
            delay_seconds=delay, phrase_text=f"шаг {step}", is_active=True,
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
    d = Dialog(client_id=client.id, type_id=dialog_type.id, ai_paused=True)
    db.add(d)
    await db.flush()
    await db.commit()
    return d


async def _say(db, dialog, role, text, *, minutes_ago, metadata=None):
    msg = Message(
        dialog_id=dialog.id, role=role, text=text,
        created_at=NOW - timedelta(minutes=minutes_ago), msg_metadata=metadata,
    )
    db.add(msg)
    dialog.last_message_at = msg.created_at
    await db.commit()
    return msg


class TestContinuesWhereItStopped:
    async def test_next_step_after_the_last_sent_ping(self, db, dialog, rules):
        """Ушёл шаг 2 — продолжаем с 4, а не с первого."""
        await _say(db, dialog, MessageRole.ai, "шаг 2", minutes_ago=600,
                   metadata={"ping": True, "funnel": "knows_price", "step": 2})
        manager = await _say(db, dialog, MessageRole.curator,
                             "Иван, жду решения по цвету", minutes_ago=60)
        state = DialogPingState(
            dialog_id=dialog.id, funnel_type="knows_price",
            current_step=4, is_completed=True,
        )
        db.add(state)
        await db.commit()

        what = await worker.resume_after_handoff(db, dialog, NOW)

        assert "продолжена с шага 4" in what
        assert state.is_completed is False
        assert state.current_step == 4
        assert state.resumed_by_manager is True
        # Отсчёт от реплики менеджера, а не от начала диалога.
        assert state.next_ping_due_at == manager.created_at + timedelta(seconds=7200)

    async def test_pause_longer_than_the_funnel_waits_out_the_silence(self, db, dialog, rules):
        """Диалог держали неделю — пинг уходит ближайшим тиком, но не мгновенно."""
        await _say(db, dialog, MessageRole.ai, "шаг 1", minutes_ago=20000,
                   metadata={"ping": True, "step": 1})
        await _say(db, dialog, MessageRole.curator, "Подобрали размер", minutes_ago=10000)
        db.add(DialogPingState(
            dialog_id=dialog.id, funnel_type="knows_price", current_step=2, is_completed=True,
        ))
        await db.commit()

        await worker.resume_after_handoff(db, dialog, NOW)

        state = await db.scalar(select(DialogPingState))
        assert state.next_ping_due_at == NOW + timedelta(seconds=worker._MIN_SILENCE_SECONDS)

    async def test_exhausted_funnel_stays_closed(self, db, dialog, rules):
        """Все шаги отправлены — продолжать нечем, но и первый заново не шлём."""
        await _say(db, dialog, MessageRole.ai, "шаг 4", minutes_ago=600,
                   metadata={"ping": True, "step": 4})
        await _say(db, dialog, MessageRole.curator, "Уточню на производстве", minutes_ago=300)
        db.add(DialogPingState(
            dialog_id=dialog.id, funnel_type="knows_price", current_step=4, is_completed=True,
        ))
        await db.commit()

        what = await worker.resume_after_handoff(db, dialog, NOW)

        state = await db.scalar(select(DialogPingState))
        assert state.is_completed is True
        assert "не осталось" in what

    async def test_untouched_funnel_starts_from_its_first_step(self, db, dialog, rules):
        """Воронка заведена, но ни один пинг не ушёл — берём назначенный шаг."""
        await _say(db, dialog, MessageRole.curator, "Отправила расчёт", minutes_ago=300)
        db.add(DialogPingState(
            dialog_id=dialog.id, funnel_type="knows_price", current_step=1, is_completed=True,
        ))
        await db.commit()

        await worker.resume_after_handoff(db, dialog, NOW)

        state = await db.scalar(select(DialogPingState))
        assert (state.current_step, state.is_completed) == (1, False)


class TestFunnelIsCreatedWhenThereIsNone:
    @pytest.fixture(autouse=True)
    def funnel_detected(self, monkeypatch):
        async def _detect(db, dialog):
            return "knows_price", "тест"

        monkeypatch.setattr("app.ping.agent.detect_funnel_with_ai", _detect)

    async def test_old_dialog_outside_the_discovery_window(self, db, dialog, rules):
        """Диалог молчит пятые сутки — discovery до него не дотянется никогда."""
        manager = await _say(db, dialog, MessageRole.curator,
                             "Держу заказ за Вами", minutes_ago=5 * 24 * 60)

        what = await worker.resume_after_handoff(db, dialog, NOW)

        state = await db.scalar(select(DialogPingState))
        assert state is not None and "заведена заново" in what
        assert state.current_step == 1
        assert state.resumed_by_manager is True
        assert state.next_ping_due_at == manager.created_at + timedelta(seconds=900)

    async def test_broadcast_is_not_a_handoff_point(self, db, dialog, rules):
        """Последним словом рассылка — это не разговор, продолжать нечего."""
        await _say(db, dialog, MessageRole.curator, "🔥 СКИДКИ ДО −70%",
                   minutes_ago=300, metadata={"broadcast": True})

        what = await worker.resume_after_handoff(db, dialog, NOW)

        assert await db.scalar(select(DialogPingState)) is None
        assert "нет наших сообщений" in what


class TestHotStageNoLongerTakesTheDialogBack:
    """Заслон горячей стадии написан против ОБЩЕЙ воронки. Диалог, который
    человек только что вернул ИИ, он забирал обратно себе — и «вне зависимости
    от статуса» не выполнялось."""

    @pytest.fixture
    def agent_ran(self, monkeypatch):
        ran = []

        async def _run(db, state, dialog):
            ran.append(state.dialog_id)
            raise AssertionError("до агента дошли — заслон не сработал")

        monkeypatch.setattr("app.ping.agent.run_ping_agent", _run)
        return ran

    async def test_resumed_dialog_is_not_escalated(self, db, dialog, rules, agent_ran):
        dialog.ai_paused = False
        dialog.funnel_stage = "checkout"
        await _say(db, dialog, MessageRole.curator, "Сумма заказа - 5 990 ₽", minutes_ago=300)
        state = DialogPingState(
            dialog_id=dialog.id, funnel_type="knows_price", current_step=1,
            resumed_by_manager=True, next_ping_due_at=NOW - timedelta(minutes=1),
        )
        db.add(state)
        await db.commit()

        with pytest.raises(AssertionError, match="заслон не сработал"):
            await worker._process_state(db, state, NOW)

        assert dialog.ai_paused is False

    async def test_ordinary_funnel_on_a_hot_stage_still_escalates(
        self, db, dialog, rules, agent_ran, monkeypatch,
    ):
        notified = []

        async def _notify(dialog_id, reason, **kwargs):
            notified.append(reason)

        monkeypatch.setattr("app.notify.notify_curator", _notify)
        dialog.ai_paused = False
        dialog.funnel_stage = "checkout"
        await _say(db, dialog, MessageRole.ai, "Сумма заказа - 5 990 ₽", minutes_ago=300)
        state = DialogPingState(
            dialog_id=dialog.id, funnel_type="knows_price", current_step=1,
            next_ping_due_at=NOW - timedelta(minutes=1),
        )
        db.add(state)
        await db.commit()

        await worker._process_state(db, state, NOW)

        assert state.is_completed is True
        assert dialog.ai_paused is True
        assert agent_ran == []
        assert notified and "горячая стадия" in notified[0]


class TestHotStageDialogGetsItsOwnFunnel:
    """Догонять горячий диалог общей воронкой — шаг назад: «Я Вам стоимость
    отправила, а вы мне что-то не отвечаете))» человеку, которому уже показали
    способы оплаты. Пока ОП не заполнил именную воронку, диалог молчит."""

    async def test_checkout_stage_switches_the_funnel(self, db, dialog, rules):
        db.add(PingRule(
            type_id=dialog.type_id, funnel_type="checkout", step=1,
            delay_seconds=1800, phrase_text="получилось выбрать способ оплаты?",
            is_active=True,
        ))
        await db.commit()
        dialog.funnel_stage = "checkout"
        await _say(db, dialog, MessageRole.curator, "Сумма заказа - 5 990 ₽", minutes_ago=10)
        db.add(DialogPingState(
            dialog_id=dialog.id, funnel_type="knows_price", current_step=2, is_completed=True,
        ))
        await db.commit()

        what = await worker.resume_after_handoff(db, dialog, NOW)

        state = await db.scalar(select(DialogPingState))
        assert state.funnel_type == "checkout"
        assert state.resumed_by_manager is True
        assert "заведена воронка «checkout»" in what

    async def test_empty_named_funnel_keeps_quiet(self, db, dialog, rules):
        """Шаги заведены, но выключены — ОП ещё не написал тексты."""
        db.add(PingRule(
            type_id=dialog.type_id, funnel_type="checkout", step=1,
            delay_seconds=1800, phrase_text="заготовка", is_active=False,
        ))
        await db.commit()
        dialog.funnel_stage = "checkout"
        await _say(db, dialog, MessageRole.curator, "Сумма заказа - 5 990 ₽", minutes_ago=10)

        what = await worker.resume_after_handoff(db, dialog, NOW)

        assert await db.scalar(select(DialogPingState)) is None
        assert "ещё не заполнена" in what

    async def test_named_funnel_already_running_is_continued_not_restarted(
        self, db, dialog, rules,
    ):
        for step, delay in ((1, 1800), (2, 10800)):
            db.add(PingRule(
                type_id=dialog.type_id, funnel_type="checkout", step=step,
                delay_seconds=delay, phrase_text=f"checkout {step}", is_active=True,
            ))
        await db.commit()
        dialog.funnel_stage = "checkout"
        await _say(db, dialog, MessageRole.ai, "checkout 1", minutes_ago=600,
                   metadata={"ping": True, "funnel": "checkout", "step": 1})
        await _say(db, dialog, MessageRole.curator, "Держу заказ", minutes_ago=10)
        db.add(DialogPingState(
            dialog_id=dialog.id, funnel_type="checkout", current_step=2, is_completed=True,
        ))
        await db.commit()

        what = await worker.resume_after_handoff(db, dialog, NOW)

        state = await db.scalar(select(DialogPingState))
        assert (state.funnel_type, state.current_step) == ("checkout", 2)
        assert "продолжена с шага 2" in what
