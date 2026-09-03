"""Вопрос про доставку не задаётся по кругу.

РОП, 03.09: «Надо пофиксить этот вопрос с доставкой, на последних этапах прям
спамит им бесконечно». Диалог 83237: клиент назвал город трижды — «Шелехов» в
20:43, «Город Шелехов» вместе с ФИО и телефоном в 21:26, «Шелехов» в 21:27, — и
каждый раз получал «В какой город нужна будет доставка?» снова.

Причин две, и обе чинятся здесь:

* список городов в коде знает 125 названий, а в России их тысячи. Шелехова в нём
  нет, слот города не заполнялся никогда;
* вопрос дописывает код, когда ход остался без вопроса вовсе (_ensure_question).
  Он брал первый незаполненный слот, не глядя на то, что этот же вопрос ушёл
  ходом раньше.

За неделю до правки: 143 диалога, где вопрос про доставку задан повторно, из них
26 — три раза и больше.
"""
import pytest

from app.ai.runner import ReplyPart, _ensure_question
from app.sales.order_slots import city_from_reply, city_named_explicitly, collect_slots

ASK_CITY = "В какой город нужна будет доставка?"
ASK_CONTACTS = (
    "Отлично, тогда подскажите, пожалуйста, ФИО и номер телефона получателя "
    "посылки, выставлю счёт на предоплату и внесу заказ в систему"
)


class TestCityOutsideTheList:
    def test_small_town_named_in_reply(self):
        """«Шелехов» — 45 тысяч жителей, ни в одном списке в коде его нет."""
        assert city_from_reply("Шелехов") == "Шелехов"

    @pytest.mark.parametrize("text,expected", [
        ("Город Шелехов", "Шелехов"),
        ("г. Шелехов", "Шелехов"),
        ("пос. Умёт", "Умёт"),
        ("Кадникова Ольга Владимировна, 89500708618\nГород Шелехов", "Шелехов"),
        ("село Красный Яр", "Красный Яр"),
    ])
    def test_city_named_by_the_word(self, text, expected):
        """Слово «город» рядом с названием ставит клиент сам — спутать не с чем,
        поэтому работает даже в одном сообщении с ФИО и телефоном."""
        assert city_named_explicitly(text) == expected

    @pytest.mark.parametrize("text", [
        "Почтой России",
        "СДЭК",
        "Доставка сколько стоит?",
        "89500708618",
        "Пункт выдачи на Ленина",
        "Мне нужно два свитшота с гербом и надписью на спине побольше",
        "Начать",
        "+",
        "Напишу позже",
        "Пока не знаю",
        "Подумаю",
        "?",
    ])
    def test_not_a_city(self, text):
        """Способ доставки, телефон, встречный вопрос и длинная фраза городом
        не считаются."""
        assert city_from_reply(text) is None

    def test_colour_is_not_a_city(self):
        """Диалог 83109: код дописал вопрос про доставку к ходу про цвет, и
        ответ «Черный» пришёл сразу после него."""
        assert city_from_reply("Черный") is None

    def test_region_counts_as_an_answer(self):
        """Клиент вправе ответить областью — вопрос он всё равно закрыл."""
        assert city_from_reply("Забайкальский край") == "Забайкальский край"


class TestCollectSlots:
    def test_city_from_the_answer_to_our_question(self):
        slots = collect_slots([
            ("manager", ASK_CITY),
            ("client", "Шелехов"),
        ])
        assert slots["city"] == "Шелехов"

    def test_city_in_one_message_with_contacts(self):
        """Диалог 83237: ФИО, телефон и город одной репликой."""
        slots = collect_slots([
            ("manager", ASK_CONTACTS + "\n\n" + ASK_CITY),
            ("client", "Кадникова Ольга Владимировна , 89500708618\nГород Шелехов"),
        ])
        assert slots["city"] == "Шелехов"
        assert slots["phone"] == "89500708618"
        assert slots["recipient"] == "Кадникова Ольга Владимировна"

    def test_answer_to_another_question_is_not_a_city(self):
        """Диалог 52: «чёрный» в ответ на вопрос про дизайн. Слот-по-очереди
        записал бы это городом."""
        slots = collect_slots([
            ("manager", "Что и где разместим на изделии?"),
            ("client", "Чёрный"),
        ])
        assert "city" not in slots

    def test_colour_answer_after_a_stray_city_question(self):
        """Тот же диалог целиком: города в нём нет, а цвет есть."""
        slots = collect_slots([
            ("manager", "Комплект из толстовки и жилетки - 8 980 ₽. " + ASK_CITY),
            ("client", "Черный"),
        ])
        assert "city" not in slots
        assert slots["color"] == "чёрный"

    def test_known_city_still_works(self):
        slots = collect_slots([("client", "Доставка в Казань")])
        assert slots["city"] == "Казань"


class TestEnsureQuestion:
    def _parts(self, text):
        return [ReplyPart(text=text, image_urls=[], message=None)]

    def test_does_not_repeat_the_question_asked_a_turn_earlier(self):
        """Даже если слот не распознан, один и тот же вопрос подряд не повторяем."""
        parts = _ensure_question(
            self._parts("Данные приняла: Кадникова Ольга Владимировна, Шелехов."),
            {},
            "test",
            [ASK_CONTACTS, ASK_CITY],
        )
        assert ASK_CITY not in parts[0].text
        assert "?" in parts[0].text

    def test_asks_the_city_when_it_was_not_asked_before(self):
        parts = _ensure_question(
            self._parts("Отличный выбор, зафиксировала."), {}, "test", ["Какое имя напишем?"],
        )
        assert ASK_CITY in parts[0].text

    def test_filled_slot_is_never_asked(self):
        parts = _ensure_question(
            self._parts("Отличный выбор, зафиксировала."),
            {"city": "Шелехов"},
            "test",
            [],
        )
        assert ASK_CITY not in parts[0].text

    def test_turn_with_a_question_is_left_alone(self):
        original = "Какой цвет выберем?"
        parts = _ensure_question(self._parts(original), {}, "test", [])
        assert parts[0].text == original
