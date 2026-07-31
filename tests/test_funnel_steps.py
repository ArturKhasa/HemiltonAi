"""Шаги воронки, которые уходят клиенту независимо от решения модели.

Диалог 52 на проде: модель ответила своим текстом вместо скрипта «2. Похвала»,
связка «похвала → стоимость → доставка» не развернулась, цена так и не ушла.
Диалог 37: контакты собраны, а вместо счёта модель написала, что ссылка «уже
отправлена ранее» — ссылки в диалоге не было ни одной.
"""
import pytest

from app.db.models import Client, Dialog, DialogType, Message, MessageRole, Script
from app.sales.funnel_steps import (
    answered_inscription_question,
    dialog_has_payment_link,
    find_payment_link_script,
    find_praise_script,
)


@pytest.fixture
async def funnel(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    price = Script(condition="2.2 Стоимость (свитшот)", phrase_text="Стоимость - 4 990 ₽", type_id=1)
    db.add(price)
    await db.flush()
    praise = Script(
        condition="ОБЯЗАТЕЛЬНЫЙ шаг воронки «2. Похвала»",
        phrase_text="Супер, зафиксировала",
        type_id=1,
        follow_up_script_id=price.id,
    )
    link = Script(
        condition="Отправляем клиенту ссылку на оплату + кр-код",
        phrase_text="Вот счет-ссылка на 500 рублей: [ссылка-оплаты]",
        type_id=1,
        funnel_stage="payment_link",
    )
    db.add_all([praise, link])
    client = Client(vk_user_id=52, name="Ирина")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, type_id=1)
    db.add(dialog)
    await db.commit()
    return {"praise": praise, "price": price, "link": link, "dialog": dialog}


class TestScriptLookup:
    async def test_praise_script_found_by_condition(self, db, funnel):
        found = await find_praise_script(db, type_id=1)
        assert found is not None and found.id == funnel["praise"].id

    async def test_payment_link_script_found_by_condition(self, db, funnel):
        found = await find_payment_link_script(db, type_id=1)
        assert found is not None and found.id == funnel["link"].id

    async def test_inactive_script_ignored(self, db, funnel):
        funnel["praise"].is_active = False
        await db.commit()
        assert await find_praise_script(db, type_id=1) is None

    async def test_other_direction_not_matched(self, db, funnel):
        assert await find_praise_script(db, type_id=2) is None


class TestPraisePoint:
    async def test_last_outgoing_is_the_inscription_question(self, db, funnel):
        db.add(Message(
            dialog_id=funnel["dialog"].id, role=MessageRole.ai,
            text="Ирина, какое имя или фамилию напишем на Вашей кофте?",
        ))
        await db.commit()
        assert await answered_inscription_question(db, funnel["dialog"].id)

    async def test_other_question_is_not_the_praise_point(self, db, funnel):
        db.add(Message(
            dialog_id=funnel["dialog"].id, role=MessageRole.ai,
            text="Какой цвет свитшота выберем?",
        ))
        await db.commit()
        assert not await answered_inscription_question(db, funnel["dialog"].id)

    async def test_client_message_does_not_count(self, db, funnel):
        """Спросить про надпись мог только менеджер — реплику клиента не читаем."""
        db.add(Message(
            dialog_id=funnel["dialog"].id, role=MessageRole.client,
            text="какое имя или фамилию напишем?",
        ))
        await db.commit()
        assert not await answered_inscription_question(db, funnel["dialog"].id)

    async def test_empty_dialog(self, db, funnel):
        assert not await answered_inscription_question(db, funnel["dialog"].id)


class TestPaymentLinkSent:
    async def test_no_link_in_empty_dialog(self, db, funnel):
        assert not await dialog_has_payment_link(db, funnel["dialog"].id)

    async def test_link_detected(self, db, funnel):
        db.add(Message(
            dialog_id=funnel["dialog"].id, role=MessageRole.ai,
            text="Вот счёт: https://example.com/pay/500",
        ))
        await db.commit()
        assert await dialog_has_payment_link(db, funnel["dialog"].id)

    async def test_promise_without_link_is_not_a_link(self, db, funnel):
        """Диалог 37: «Ссылка на оплату уже отправлена ранее» — а ссылки не было."""
        db.add(Message(
            dialog_id=funnel["dialog"].id, role=MessageRole.ai,
            text="Ссылка на оплату уже отправлена ранее - внесите предоплату.",
        ))
        await db.commit()
        assert not await dialog_has_payment_link(db, funnel["dialog"].id)
