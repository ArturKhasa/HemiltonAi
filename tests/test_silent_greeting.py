"""Клиент молчит после вопроса про имя — через 15 минут уходит цена.

Правило Лены от 17.08. Диалог 346: клиент нажал «Начать» в 11:41, получил
приветствие и вопрос про надпись и замолчал — за пять часов ему не ушло ничего,
потому что воронка пингов до отправки цены заблокирована.
"""
from datetime import timedelta

import pytest

from app.db.models import (
    Client, Dialog, DialogType, Message, MessageRole, Script, VkGroup,
)
from app.ping.silent_greeting import (
    SILENCE_SECONDS, _greeting_unanswered, find_price_script,
)
from app.utils.time import msk_now

NAME_QUESTION = "Какое имя или фамилию напишем на Вашей кофте?"


@pytest.fixture
async def funnel(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add_all([
        Script(
            id=363, is_active=True, type_id=1, funnel_stage="greeting",
            condition="2. Похвала", phrase_text="Супер, зафиксировала",
            follow_up_script_id=367,
        ),
        Script(
            id=367, is_active=True, type_id=1, funnel_stage="pricing",
            condition="2.2 Стоимость (свитшот)",
            phrase_text="Стоимость толстовки со скидкой СЕГОДНЯ - 5 990 ₽",
            follow_up_script_id=372,
        ),
        Script(
            id=372, is_active=True, type_id=1, funnel_stage="pricing",
            condition="2.3 Доставка", phrase_text="В какой город нужна доставка?",
        ),
    ])
    await db.flush()
    return db


async def _dialog_with_greeting(db, *, minutes_ago: int, last_role=MessageRole.ai,
                                last_text=NAME_QUESTION):
    group = VkGroup(group_id=111222, name="Магазин", access_token="t", confirmation_code="c")
    db.add(group)
    await db.flush()
    client = Client(vk_user_id=555, vk_group_id=group.id)
    db.add(client)
    await db.flush()
    sent_at = msk_now() - timedelta(minutes=minutes_ago)
    dialog = Dialog(client_id=client.id, type_id=1, funnel_stage="greeting",
                    last_message_at=sent_at)
    db.add(dialog)
    await db.flush()
    db.add(Message(
        dialog_id=dialog.id, role=last_role, text=last_text, created_at=sent_at,
    ))
    await db.flush()
    return dialog


class TestPriceScriptLookup:
    async def test_found_through_the_greeting_chain(self, funnel):
        """Ищем не по id: в админке скрипты пересоздают."""
        script = await find_price_script(funnel, type_id=1)
        assert script is not None and script.id == 367

    async def test_none_when_chain_is_not_configured(self, db):
        db.add(DialogType(id=1, name="default", display_name="Основное"))
        db.add(Script(
            id=999, is_active=True, type_id=1, funnel_stage="pricing",
            condition="Стоимость без связки", phrase_text="5 990 ₽",
        ))
        await db.flush()
        assert await find_price_script(db, type_id=1) is None


class TestSilenceCheck:
    async def test_fifteen_minutes_of_silence_qualifies(self, funnel):
        dialog = await _dialog_with_greeting(funnel, minutes_ago=16)
        assert await _greeting_unanswered(funnel, dialog, msk_now()) is True

    async def test_fresh_question_waits(self, funnel):
        dialog = await _dialog_with_greeting(funnel, minutes_ago=5)
        assert await _greeting_unanswered(funnel, dialog, msk_now()) is False

    async def test_client_answered_nothing_to_do(self, funnel):
        dialog = await _dialog_with_greeting(
            funnel, minutes_ago=30, last_role=MessageRole.client, last_text="Вова Чудаев",
        )
        assert await _greeting_unanswered(funnel, dialog, msk_now()) is False

    async def test_our_last_message_is_not_the_name_question(self, funnel):
        dialog = await _dialog_with_greeting(
            funnel, minutes_ago=30, last_text="Стоимость толстовки - 5 990 ₽",
        )
        assert await _greeting_unanswered(funnel, dialog, msk_now()) is False

    def test_wait_is_the_agreed_fifteen_minutes(self):
        assert SILENCE_SECONDS == 15 * 60


class TestSending:
    async def test_price_and_its_chain_go_out_and_are_marked(self, funnel, monkeypatch):
        from sqlalchemy import select

        from app.ping.silent_greeting import _send_price
        from app.vk.sender import SentMessage

        sent: list[str] = []

        async def _fake_send(db_, dialog_, text):
            sent.append(text)
            return SentMessage(message_id=900 + len(sent), random_ids=[123])

        monkeypatch.setattr("app.ping.silent_greeting.send_to_dialog", _fake_send)

        dialog = await _dialog_with_greeting(funnel, minutes_ago=20)
        script = await find_price_script(funnel, type_id=1)

        assert await _send_price(funnel, dialog, script, msk_now()) is True

        # Ушла стоимость и следом связанное с ней звено про доставку.
        assert any("5 990" in t for t in sent)
        assert any("город" in t for t in sent)
        # Диалог больше не «без цены» — обычные пинги теперь ему полагаются.
        assert dialog.funnel_stage == "pricing"
        saved = (await funnel.execute(
            select(Message).where(Message.role == MessageRole.ai)
        )).scalars().all()
        price_msg = next(m for m in saved if "5 990" in (m.text or ""))
        assert price_msg.msg_metadata["delivered"] is True

    async def test_failed_send_leaves_nothing_marked_delivered(self, funnel, monkeypatch):
        from app.ping.silent_greeting import _send_price

        async def _boom(db_, dialog_, text):
            raise RuntimeError("VK down")

        monkeypatch.setattr("app.ping.silent_greeting.send_to_dialog", _boom)

        dialog = await _dialog_with_greeting(funnel, minutes_ago=20)
        script = await find_price_script(funnel, type_id=1)

        assert await _send_price(funnel, dialog, script, msk_now()) is False
        assert dialog.funnel_stage == "greeting"
