"""Форма одного хода: один вопрос, без дублей, без повторных предложений.

Замечания ОП от 10 августа:
- 13:51: «Два вопроса подряд нельзя задавать. Сначала очень важно увидеть ответ
  на первый вопрос, затем задавать второй».
- 13:45: «Дубль полного скрипта. Вместо него можно было задублировать только
  вопрос про удобный способ оплаты».
- 13:42 и 13:53: «Нет вопроса. Они обязательно должны быть после каждого
  сообщения, чтобы диалог продолжался».
- 13:53: «Примерно четвёртое предложение о бесплатном макете в этом диалоге».
"""
from dataclasses import dataclass, field

import pytest

from app.ai.runner import (
    _drop_duplicate_parts,
    _drop_repeated_offers,
    _ensure_question,
    _keep_one_question,
    awaits_client_answer,
)
from app.sales.funnel_steps import client_wants_design_edit


@dataclass
class FakePart:
    text: str
    image_urls: list = field(default_factory=list)


def _texts(parts):
    return [p.text for p in parts]


class TestAwaitsAnswer:
    @pytest.mark.parametrize("text", [
        "Приняла: толстовка серого цвета, герб на спине. Всё верно?",
        "Хорошо, зафиксировала Ваши пожелания. Что именно изменяем в дизайне?",
        "Правильно понимаю, что берём чёрный?",
    ])
    def test_verification_question_holds_the_turn(self, text):
        """На такой реплике ход заканчивается — следующий шаг воронки отвечал бы
        на согласие, которого клиент ещё не давал."""
        assert awaits_client_answer(text)

    @pytest.mark.parametrize("text", [
        "Супер, зафиксировала! Сделаем всё как Вы хотите!",
        "В какой город нужна будет доставка?",
        "Какой цвет выберем?",
    ])
    def test_ordinary_question_does_not_hold_the_turn(self, text):
        assert not awaits_client_answer(text)


class TestDesignEdit:
    @pytest.mark.parametrize("text", [
        "Изменить дизайн",
        "Буквы Гера зачем ставить сказал же не нужно !!!",
        "Почему взади Гера кайф должно Россия кайф по английский пожалуйста переделайте",
        "Уберите герб со спины",
    ])
    def test_edit_request_is_not_a_confirmation(self, text):
        assert client_wants_design_edit(text)

    @pytest.mark.parametrize("text", [
        "Да все верно", "Черный или серый", "Рост 164 весь 55", "Сначало 500",
    ])
    def test_ordinary_replies_are_not_edit_requests(self, text):
        assert not client_wants_design_edit(text)


class TestDuplicateParts:
    def test_identical_script_is_reduced_to_its_question(self):
        """Диалог 142, 10:01: один и тот же скрипт оформления ушёл дважды подряд."""
        checkout = (
            "Получается сумма заказа - 4 990 ₽\n\n"
            "А по оплате у нас есть 2 удобных варианта: всю сумму сразу с подарком "
            "или первая оплата 500 рублей.\n\n"
            "Удобно оплатить всю сумму сразу с подарком или сначала 500 рублей?"
        )
        parts = [FakePart(checkout)]

        got = _texts(_drop_duplicate_parts(parts, [checkout], "ctx"))

        assert got == ["Удобно оплатить всю сумму сразу с подарком или сначала 500 рублей?"]

    def test_fresh_text_survives(self):
        parts = [FakePart("Чёрный зафиксировала. Какой у Вас рост и вес?")]
        assert len(_drop_duplicate_parts(parts, ["Совсем другое сообщение"], "ctx")) == 1


class TestEnsureQuestion:
    def test_turn_without_a_question_gets_one(self):
        """Диалог 142, 13:19: прайс ушёл, звено «Доставка» пропустилось как
        известное, и ход остался без вопроса — клиенту нечего ответить."""
        parts = [FakePart("Стоимость толстовки со скидкой СЕГОДНЯ - 5 990 ₽.")]

        got = _texts(_ensure_question(parts, {}, "ctx"))

        assert got[0].endswith("В какой город нужна будет доставка?")

    def test_question_asks_about_what_is_still_unknown(self):
        parts = [FakePart("Стоимость - 5 990 ₽.")]
        got = _texts(_ensure_question(parts, {"city": "Казань"}, "ctx"))
        assert got[0].endswith("Какой цвет выберем?")

    def test_existing_question_is_left_alone(self):
        parts = [FakePart("Какой цвет выберем?")]
        assert _texts(_ensure_question(parts, {}, "ctx")) == ["Какой цвет выберем?"]


class TestRepeatedOffers:
    def test_free_mockup_is_offered_once(self):
        history = ["Давайте сделаем бесплатный макет, чтобы Вы сразу понимали, как будет смотреться?"]
        parts = [FakePart(
            "Понимаю Вас. Могу предложить бесплатный макет с Вашим дизайном. "
            "В какой город нужна доставка?"
        )]

        got = _texts(_drop_repeated_offers(parts, history, "ctx"))

        assert "макет" not in got[0].lower()
        assert "В какой город нужна доставка?" in got[0]

    def test_offer_not_yet_made_survives(self):
        parts = [FakePart("Давайте сделаем бесплатный макет?")]
        assert len(_drop_repeated_offers(parts, ["Стоимость - 5 990 ₽"], "ctx")) == 1


class TestOneQuestionPerTurn:
    """ОП, документ от 11 августа, п. 2: «ии всегда дожидается ответ на вопрос,
    потом задает следующий/отправляет следующий скрипт. На скрине задала 2
    вопроса подряд»."""

    def test_second_question_is_stripped(self):
        parts = [
            FakePart("Чёрный зафиксировала. Какой у Вас рост и вес?"),
            FakePart("Кстати, а в какой город доставка?"),
        ]

        got = _texts(_keep_one_question(parts, "ctx"))

        assert got[0].endswith("Какой у Вас рост и вес?")
        assert "?" not in "".join(got[1:])

    def test_two_questions_inside_one_message_leave_the_first(self):
        parts = [FakePart("Какой цвет выберем? И какой у Вас рост?")]
        got = _texts(_keep_one_question(parts, "ctx"))
        assert got == ["Какой цвет выберем? И какой у Вас рост?"]

    def test_the_regulation_chain_survives(self):
        """Похвала, стоимость и доставка уходят подряд по регламенту — вопрос в
        них ровно один, в последнем звене, и он обязан остаться."""
        parts = [
            FakePart("Супер, зафиксировала! Сделаем всё как Вы хотите!"),
            FakePart("Стоимость толстовки со скидкой СЕГОДНЯ - 5 990 ₽"),
            FakePart("Шьём по Вашим меркам.\n\nВ какой город нужна будет доставка?"),
        ]

        got = _texts(_keep_one_question(parts, "ctx"))

        assert len(got) == 3
        assert got[-1].endswith("В какой город нужна будет доставка?")

    def test_part_left_without_text_but_with_a_photo_survives(self):
        parts = [
            FakePart("Какой цвет выберем?"),
            FakePart("А рост и вес?", image_urls=["https://example.ru/a.jpg"]),
        ]

        got = _keep_one_question(parts, "ctx")

        assert len(got) == 2
        assert got[1].text == ""
        assert got[1].image_urls
