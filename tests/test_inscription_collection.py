"""Надпись, названная несколькими сообщениями подряд.

Диалог 351, 17.08: на «какое имя или фамилию напишем на Вашей кофте?» клиент
ответил «Фамилию», а через тринадцать секунд — «Шаманский». В заказ попало
первое слово, и на согласование дизайна ушло «Надпись „Фамилию“ на чёрном
свитшоте».
"""
from app.sales.order_slots import collect_slots

ASK = ("manager", "Виктор, какое имя или фамилию напишем на Вашей кофте?")


def test_choice_word_is_not_the_inscription():
    slots = collect_slots([ASK, ("client", "Фамилию"), ("client", "Шаманский")])
    assert slots["inscription"] == "Шаманский"


def test_inscription_split_across_two_messages_is_joined():
    slots = collect_slots([ASK, ("client", "Иван"), ("client", "Петров")])
    assert slots["inscription"] == "Иван Петров"


def test_single_message_answer_unchanged():
    slots = collect_slots([ASK, ("client", "Шаманский")])
    assert slots["inscription"] == "Шаманский"


def test_our_next_message_closes_the_collection():
    slots = collect_slots([
        ASK,
        ("client", "Шаманский"),
        ("manager", "Супер, зафиксировала"),
        ("client", "Чёрный"),
    ])
    assert slots["inscription"] == "Шаманский"
    assert slots["color"] == "чёрный"


def test_counter_question_is_not_collected():
    slots = collect_slots([ASK, ("client", "Шаманский"), ("client", "А сколько стоит?")])
    assert slots["inscription"] == "Шаманский"


def test_long_phrase_is_not_an_inscription():
    slots = collect_slots([
        ASK,
        ("client", "Хочу посмотреть сначала что у вас есть по дизайнам"),
    ])
    assert "inscription" not in slots


def test_choice_word_alone_leaves_the_slot_empty():
    assert "inscription" not in collect_slots([ASK, ("client", "Имя")])
