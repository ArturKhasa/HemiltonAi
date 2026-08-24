"""Цена считается названной, только если сообщение с ней дошло до клиента.

Диалог 78880, 24.08 10:07. Клиент ответил двумя сообщениями подряд — «Фамилия
Никиточкин» и «Имя Никита». Первый прогон отменился на середине, и вся связка
(похвала → стоимость → доставка) осталась недоставленной. Но сумма за диалогом
уже закрепилась, и второй прогон вычеркнул прайс как «уже отправленный»: клиент
получил похвалу и вопрос про город без единой цифры.

Лена, 24.08: «Привет, ИИ перестала цену отправлять».
"""
import pytest

from app.db.models import Client, Dialog, DialogType, Message, MessageRole
from app.sales.funnel_steps import delivered_outgoing_texts
from app.vk.outgoing import mark_failed

PRICE = "Стоимость толстовки с термо-принтами со скидкой СЕГОДНЯ - 5 990 ₽ (вместо 7 990 ₽)"


@pytest.fixture
async def dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add(Client(id=1, vk_user_id=555, name="Никита"))
    await db.flush()
    d = Dialog(id=1, client_id=1, type_id=1)
    db.add(d)
    await db.flush()
    return d


class TestDeliveredOutgoingTexts:
    async def test_failed_message_is_not_counted_as_sent(self, db, dialog):
        failed = Message(dialog_id=dialog.id, role=MessageRole.ai, text=PRICE)
        mark_failed(failed)
        db.add(failed)
        await db.flush()

        texts = await delivered_outgoing_texts(db, dialog.id)
        assert texts == [], "недоставленная цена не должна считаться названной"

    async def test_delivered_message_is_counted(self, db, dialog):
        db.add(Message(dialog_id=dialog.id, role=MessageRole.ai, text=PRICE))
        await db.flush()

        texts = await delivered_outgoing_texts(db, dialog.id)
        assert any("5 990" in t for t in texts)

    async def test_only_the_failed_one_drops_out(self, db, dialog):
        failed = Message(dialog_id=dialog.id, role=MessageRole.ai, text=PRICE)
        mark_failed(failed)
        db.add(failed)
        db.add(Message(
            dialog_id=dialog.id, role=MessageRole.ai,
            text="Супер, зафиксировала\nСделаем всё как Вы хотите!",
        ))
        await db.flush()

        texts = await delivered_outgoing_texts(db, dialog.id)
        assert len(texts) == 1
        assert "5 990" not in texts[0]
