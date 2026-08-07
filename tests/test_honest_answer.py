"""Ответ цифрой на пинговый список «давайте начистоту, из-за чего молчите?».

Клиент 44731492 ответил «1» — «Заказ не актуален», и разговор продолжил ИИ,
хотя дальше по регламенту подключается человек (диалог 111, 10:40). Для модели
«1» — просто символ: список остаётся в истории, но смысла цифре это не придаёт.
"""
import pytest

from app.db.models import Dialog, Message, MessageRole
from app.sales.funnel_steps import (
    HONEST_CURATOR_OPTIONS,
    HONEST_OPTIONS,
    honest_answer,
)

HONEST_LIST = (
    "Давайте начистоту, из-за чего молчите?\n\n"
    "1. Заказ не актуален\n2. Сомневаюсь в предоплате\n3. У вас дорого\n"
    "4. Планирую делать заказ позже\n5. Нет времени пообщаться\n"
    "6. Думаю что вы мошенники\n7. Другое..."
)


@pytest.fixture
async def dialog(db):
    d = Dialog(client_id=1, type_id=1)
    db.add(d)
    await db.commit()
    return d


async def _say(db, dialog, text, role=MessageRole.ai):
    db.add(Message(dialog_id=dialog.id, role=role, text=text))
    await db.commit()


class TestHonestAnswer:
    @pytest.mark.parametrize("digit", list("1234567"))
    async def test_digit_after_the_list_is_read_as_a_choice(self, db, dialog, digit):
        await _say(db, dialog, HONEST_LIST)
        assert await honest_answer(db, dialog.id, digit) == digit

    async def test_digit_survives_punctuation(self, db, dialog):
        await _say(db, dialog, HONEST_LIST)
        assert await honest_answer(db, dialog.id, " 3.") == "3"

    async def test_digit_without_the_list_means_nothing(self, db, dialog):
        """«2» в ответ на «сколько изделий?» — это количество, а не причина."""
        await _say(db, dialog, "Сколько изделий планируете?")
        assert await honest_answer(db, dialog.id, "2") is None

    async def test_words_are_not_a_choice(self, db, dialog):
        await _say(db, dialog, HONEST_LIST)
        assert await honest_answer(db, dialog.id, "дорого у вас") is None

    async def test_out_of_range_digit_is_not_a_choice(self, db, dialog):
        await _say(db, dialog, HONEST_LIST)
        assert await honest_answer(db, dialog.id, "9") is None

    def test_curator_options_are_the_two_the_ai_must_not_work(self):
        assert HONEST_CURATOR_OPTIONS == {"1", "6"}
        assert HONEST_OPTIONS["1"] == "Заказ не актуален"
        assert HONEST_OPTIONS["6"] == "Думаю что вы мошенники"
