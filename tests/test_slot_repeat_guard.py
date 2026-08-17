"""Один и тот же запрос данных третий раз подряд.

Диалог 343, 17.08, 90 секунд: три сообщения подряд с просьбой прислать ФИО и
телефон — разными словами, поэтому защита от дублей их не увидела. Клиент в это
время спрашивал про макет и выбирал подарок.
"""
import pytest

from app.ai.runner import repeats_slot_request

ASK_1 = "Для оформления пришлите, пожалуйста, ФИО и телефон получателя, что скажете?"
ASK_2 = "Напишете ФИО и телефон получателя?"
ASK_3 = "Пришлите, пожалуйста, ФИО и телефон получателя для оформления заказа?"


def test_third_ask_in_a_row_caught():
    assert repeats_slot_request(ASK_3, [ASK_1, ASK_2], {}) == "recipient"


def test_second_ask_allowed():
    """Второй раз — клиент мог не заметить сообщение."""
    assert repeats_slot_request(ASK_2, [ASK_1], {}) is None


def test_ask_interrupted_by_another_topic_allowed():
    other = "Да, перед изготовлением согласуем макет. Какой подарок выбираете?"
    assert repeats_slot_request(ASK_3, [ASK_1, other], {}) is None


def test_slot_already_filled_is_not_a_repeat():
    """Данные пришли — реплика их подтверждает, а не просит заново."""
    slots = {"recipient": "Чудаев Владимир Валерьевич", "phone": "89967246316"}
    assert repeats_slot_request(ASK_3, [ASK_1, ASK_2], slots) is None


def test_other_slots_counted_separately():
    city = "В какой город нужна доставка?"
    assert repeats_slot_request(city, [ASK_1, ASK_2], {}) is None


def test_city_repeated_three_times_caught():
    city = "В какой город доставляем?"
    assert repeats_slot_request(city, [city, "Город доставки подскажете?"], {}) == "city"


@pytest.mark.parametrize("history", [[], [ASK_1]])
def test_short_history_never_fires(history):
    assert repeats_slot_request(ASK_2, history, {}) is None
