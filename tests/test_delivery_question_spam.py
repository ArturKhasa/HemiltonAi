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

from app.ai.runner import ReplyPart, _ensure_question, asks_known_slot
from app.sales.order_slots import city_named_explicitly, collect_slots

ASK_CITY = "В какой город нужна будет доставка?"
ASK_CONTACTS = (
    "Отлично, тогда подскажите, пожалуйста, ФИО и номер телефона получателя "
    "посылки, выставлю счёт на предоплату и внесу заказ в систему"
)


class TestCityOutsideTheList:
    @pytest.mark.parametrize("text,expected", [
        ("Город Шелехов", "Шелехов"),
        ("г. Шелехов", "Шелехов"),
        ("пос. Умёт", "Умёт"),
        ("Кадникова Ольга Владимировна, 89500708618\nГород Шелехов", "Шелехов"),
        ("село Красный Яр", "Красный Яр"),
    ])
    def test_city_named_by_the_word(self, text, expected):
        """Слово «город» рядом с названием ставит клиент сам — спутать не с чем,
        поэтому работает даже в одном сообщении с ФИО и телефоном. Шелехова нет
        ни в одном списке в коде: 45 тысяч жителей."""
        assert city_named_explicitly(text) == expected

    @pytest.mark.parametrize("text", [
        "Ненужно",
        "Покажите ассортимент ваших товаров",
        "Пару",
        "Вышивка нитками",
        "Начать",
        "Почтой России",
    ])
    def test_free_answer_is_not_taken_as_a_city(self, text):
        """Ответ на вопрос про доставку слотом НЕ становится: на боевых данных
        так записались «Ненужно», «Покажите ассортимент ваших товаров» и «Пару»
        — последнее ИИ вернул клиенту как «По Пару доставляем СДЭКом». Выдуманный
        за клиента факт хуже лишнего вопроса."""
        assert "city" not in collect_slots([("manager", ASK_CITY), ("client", text)])


class TestCollectSlots:
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
        """Диалог 83109: код дописал вопрос про доставку к ходу про цвет."""
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

    def test_does_not_repeat_a_question_already_asked(self):
        """Слот не распознан, но вопрос уже задавали — второй раз не дописываем."""
        parts = _ensure_question(
            self._parts("Данные приняла: Кадникова Ольга Владимировна, Шелехов."),
            {},
            "test",
            [ASK_CONTACTS, ASK_CITY],
        )
        assert ASK_CITY not in parts[0].text
        assert "?" in parts[0].text

    def test_looks_at_the_whole_history_not_just_the_last_turns(self):
        """Диалог 83237: между двумя вопросами про доставку прошло полтора часа
        и десяток реплик."""
        parts = _ensure_question(
            self._parts("Зафиксировала размер!"),
            {},
            "test",
            [ASK_CITY] + [f"Реплика {i}" for i in range(8)],
        )
        assert ASK_CITY not in parts[0].text

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


class TestAsksKnownSlot:
    """Диалог 82260: клиент назвал Екатеринбург, через две реплики ИИ спросил
    «В какой город нужна доставка?», а ещё через две сам написал «в Екатеринбург
    доставляем». Вопрос о заполненном слоте — сбой хода, а не забывчивость."""

    def test_asking_about_a_known_city(self):
        assert asks_known_slot(ASK_CITY, {"city": "Екатеринбург"}) == "city"

    def test_asking_about_an_unknown_city_is_fine(self):
        assert asks_known_slot(ASK_CITY, {}) is None

    def test_asking_about_known_contacts(self):
        slots = {"recipient": "Кадникова Ольга Владимировна", "phone": "89500708618"}
        assert asks_known_slot(ASK_CONTACTS, slots) == "recipient"

    def test_half_of_the_contacts_is_not_enough(self):
        """Скрипт спрашивает ФИО и телефон одной фразой — половины ответа мало."""
        assert asks_known_slot(ASK_CONTACTS, {"recipient": "Кадникова Ольга"}) is None

    def test_ordinary_reply_passes(self):
        assert asks_known_slot("Какой цвет выберем?", {"city": "Казань"}) is None
