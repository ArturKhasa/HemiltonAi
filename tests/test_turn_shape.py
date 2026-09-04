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
import pytest

from app.ai.runner import (
    ReplyPart,
    _drop_duplicate_parts,
    _drop_repeated_offers,
    _ensure_question,
    _keep_one_question,
    awaits_client_answer,
)
from app.sales.funnel_steps import client_wants_design_edit


def FakePart(text, image_urls=None):
    """Настоящая часть хода без строки в базе: гейты правят и то, и другое."""
    return ReplyPart(text=text, image_urls=image_urls or [], message=None)


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

    def test_data_collection_reply_gets_its_own_fallback_question(self):
        """Скрин ОП, 04.09 (PLAN-2026-09-04-pravki-OP.md, пункт D): скрипт «5.1
        Данные перед оформлением» построен без «?» («Отлично, тогда
        подскажите...»), и без этой ветки общий фолбэк по товарным слотам
        приклеивал «Какой цвет выберем?» тем же сообщением, где уже просят
        ФИО и телефон. Лена, 04.09 11:30: «На этапе запроса данных вопрос —
        Получится сейчас?»."""
        parts = [FakePart(
            "Отлично, тогда подскажите, пожалуйста, ФИО и номер телефона "
            "получателя посылки, выставлю счёт на предоплату и внесу заказ в "
            "систему"
        )]
        got = _texts(_ensure_question(parts, {"color": "чёрный"}, "ctx"))
        assert got[0].endswith("Получится сейчас?")
        assert "цвет" not in got[0].lower()


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

    def test_two_questions_inside_one_message_keep_only_the_first(self):
        """До 04.09 два вопроса в ОДНОЙ части не резались вовсе (резали только
        между частями) — «Отлично, тогда подскажите ФИО и телефон получателя...
        Какой цвет выберем?» уходило клиенту целиком (скрин ОП,
        PLAN-2026-09-04-pravki-OP.md, пункт D)."""
        parts = [FakePart("Какой цвет выберем? И какой у Вас рост?")]
        got = _texts(_keep_one_question(parts, "ctx"))
        assert got == ["Какой цвет выберем?"]


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


# Ссылка на картинку в скрипте кончается на «…RoMf.jpg?quality=95&as=32x53,…» —
# внутри неё живёт свой «вопрос».
PHOTO = (
    "[photo-https://sun9-30.vkuserphoto.ru/s/v1/ig2/AbwtA1sC3ebMeBIulTma4C.jpg"
    "?quality=95&as=32x53,48x79&from=bu&cs=539x0&attachment=photo-44440184_457423774]"
)


class TestAttachmentTokensAreNotQuestions:
    """Клиент вместо суммы заказа получил одно слово «jpg?».

    Диалог 75800, 20.08 23:19: скрипт оформления уходил повторно, дубль свернулся
    «до последнего вопроса», а последним вопросом оказался хвост ссылки. В базе
    при этом лежал полный текст со статусом «доставлено».
    """

    CHECKOUT = (
        "Получается сумма заказа - 5 990 ₽\n\n"
        "Прикрепляю наши отзывы!\n\n"
        "Удобно оплатить всю сумму сразу с подарком или сначала 500 рублей?)\n\n"
        f"{PHOTO}"
    )

    def test_duplicate_collapses_to_the_real_question(self):
        parts = [FakePart(self.CHECKOUT)]

        got = _texts(_drop_duplicate_parts(parts, [self.CHECKOUT], "ctx"))

        assert got[0].startswith("Удобно оплатить всю сумму сразу с подарком")
        assert "jpg?" not in got[0].split("[photo-")[0]

    def test_pictures_survive_the_collapse(self):
        parts = [FakePart(self.CHECKOUT)]

        got = _texts(_drop_duplicate_parts(parts, [self.CHECKOUT], "ctx"))

        # Картинки к вопросу про оплату — это отзывы, уходят ровно с ним.
        assert PHOTO in got[0]

    def test_photo_only_part_does_not_spend_the_turn_question(self):
        parts = [
            FakePart(f"Стоимость толстовки - 5 990 ₽\n\n{PHOTO}"),
            FakePart("Шьём по Вашим меркам.\n\nВ какой город нужна будет доставка?"),
        ]

        got = _texts(_keep_one_question(parts, "ctx"))

        assert got[1].endswith("В какой город нужна будет доставка?")
        assert PHOTO in got[0]

    def test_link_is_not_torn_apart_as_a_repeated_question(self):
        parts = [
            FakePart("В какой город нужна будет доставка?"),
            FakePart(f"Стоимость толстовки - 5 990 ₽\n\n{PHOTO}"),
        ]

        got = _texts(_keep_one_question(parts, "ctx"))

        # Раньше «jpg?» вырезалось из середины ссылки, токен становился мусорным
        # и картинка молча пропадала.
        assert PHOTO in got[1]

    def test_turn_of_pictures_alone_still_gets_a_question(self):
        parts = [FakePart(f"Вот наши работы\n\n{PHOTO}")]

        got = _texts(_ensure_question(parts, {}, "ctx"))

        assert got[0].endswith("В какой город нужна будет доставка?")


class TestPanelShowsWhatTheClientGot:
    """Гейты правят и строку в базе: иначе ОП разбирает диалог по тексту,
    которого клиент не видел (сообщение 160076 против «jpg?» в ВК)."""

    class FakeMessage:
        def __init__(self, text):
            self.text = text

    def _part(self, text):
        message = self.FakeMessage(text)
        return ReplyPart(text=text, image_urls=[], message=message), message

    def test_collapsed_duplicate_is_rewritten_in_the_database(self):
        checkout = (
            "Получается сумма заказа - 5 990 ₽\n\n"
            "Удобно оплатить всю сумму сразу с подарком или сначала 500 рублей?"
        )
        part, message = self._part(checkout)

        _drop_duplicate_parts([part], [checkout], "ctx")

        assert message.text == part.text
        assert message.text.startswith("Удобно оплатить")

    def test_stripped_second_question_is_rewritten_in_the_database(self):
        first, _ = self._part("Какой цвет выберем?")
        second, message = self._part("Шьём по меркам.\n\nВ какой город доставка?")

        _keep_one_question([first, second], "ctx")

        assert message.text == "Шьём по меркам."

    def test_appended_question_is_rewritten_in_the_database(self):
        part, message = self._part("Супер, зафиксировала")

        _ensure_question([part], {"city": "Казань", "color": "чёрный"}, "ctx")

        assert message.text == part.text
        assert message.text.endswith("?")
