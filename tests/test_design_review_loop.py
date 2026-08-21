"""Сверка «Всё верно?» по кругу и картинка, которой клиент не видел.

Диалог 75853, 21.08. Клиент четырежды написал, что примера с надписями не видит,
и четырежды получил ту же сверку — каждый раз переписанную заново, поэтому
защита от дублей её не ловила. К пятой он ответил «Удачи с вашими тупыми ботами».

Отправлено ему было стоковое фото белых свитшотов без единой надписи, а ответы
уверяли, что «фото-пример с этими именами и фамилиями уже отправила».
"""
import pytest

from app.db.models import Client, Dialog, DialogType, Message, MessageRole, VkGroup
from app.sales.funnel_steps import asks_confirmation, confirmations_in_a_row
from app.sales.product_photo import claims_picture_already_sent, reply_shows_photo


@pytest.fixture
async def dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    group = VkGroup(group_id=44440184, name="Hemilton", access_token="t", confirmation_code="c")
    db.add(group)
    await db.flush()
    client = Client(vk_user_id=90309045, vk_group_id=group.id, name="Кирилл")
    db.add(client)
    await db.flush()
    row = Dialog(client_id=client.id, type_id=1, funnel_stage="design")
    db.add(row)
    await db.flush()
    return row


def _ours(dialog, text):
    return Message(dialog_id=dialog.id, role=MessageRole.ai, text=text)


class TestAsksConfirmation:
    @pytest.mark.parametrize("text", [
        "Зафиксировала размеры! На белом свитшоте разместим имена. Всё верно?",
        "Поняла, тогда делаем два белых свитшота без надписей. Все верно?",
    ])
    def test_verification_recognised(self, text):
        assert asks_confirmation(text)

    @pytest.mark.parametrize("text", [
        "Всё верно, передаю в работу.",          # утверждение, не вопрос
        "Какой цвет свитшота выберем?",
    ])
    def test_other_replies_are_not_verification(self, text):
        assert not asks_confirmation(text)


class TestConfirmationStreak:
    async def test_counts_only_the_trailing_run(self, db, dialog):
        db.add_all([
            _ours(dialog, "Какой цвет свитшота выберем?"),
            _ours(dialog, "Разместим имена и фамилии на белых свитшотах. Всё верно?"),
            _ours(dialog, "Делаем два белых свитшота без надписей. Всё верно?"),
        ])
        await db.commit()

        assert await confirmations_in_a_row(db, dialog.id) == 2

    async def test_a_normal_reply_resets_the_streak(self, db, dialog):
        db.add_all([
            _ours(dialog, "Разместим имена и фамилии. Всё верно?"),
            _ours(dialog, "Да, покажу макет перед изготовлением. На груди или на спине?"),
        ])
        await db.commit()

        assert await confirmations_in_a_row(db, dialog.id) == 0

    async def test_empty_dialog(self, db, dialog):
        assert await confirmations_in_a_row(db, dialog.id) == 0

    async def test_undelivered_verification_does_not_count(self, db, dialog):
        held = _ours(dialog, "Разместим имена. Всё верно?")
        held.msg_metadata = {"delivered": False, "delivery_failed": True}
        db.add(held)
        await db.commit()

        assert await confirmations_in_a_row(db, dialog.id) == 0


class TestPictureClaims:
    @pytest.mark.parametrize("text", [
        "Фото-пример с этими именами и фамилиями уже отправила. Всё верно?",
        "Фото отправилось выше в переписке, отдельным сообщением.",
        "Макет я Вам уже показала ранее.",
    ])
    def test_referring_to_a_past_picture_is_caught(self, text):
        assert claims_picture_already_sent(text)

    @pytest.mark.parametrize("text", [
        "Покажу пример белого свитшота с нанесением имён:",
        "Счёт на предоплату уже отправлен, проверьте, пожалуйста.",
        "Какой цвет свитшота выберем?",
    ])
    def test_other_replies_are_left_alone(self, text):
        assert not claims_picture_already_sent(text)

    def test_a_reply_with_the_picture_attached_is_fine(self):
        """Гейт срабатывает только когда картинки в ответе нет."""
        text = (
            "Отправляю пример ещё раз\n\n"
            "[photo-https://ai.hemilton.ru/media/scripts/a3eb.jpg]"
        )
        assert reply_shows_photo(text)
