"""Сбор уже названных клиентом фактов заказа.

Материал — диалог 52 на проде: клиент назвал надпись, город, цвет, размер, ФИО и
телефон, а модель пять ходов подряд спрашивала «какой дизайн нанесём на кофту?»
и следом переспросила город. Все эти факты извлекаются из истории механически,
поэтому и извлекаются кодом.
"""
import pytest

from app.sales.order_slots import ASKS_CITY_RE, collect_slots, format_slots_block

# Реальная последовательность диалога 52 (сообщения 664-678).
DIALOG_52 = [
    ("manager", "Ирина, какое имя или фамилию напишем на Вашей кофте?"),
    ("client", "Соколова"),
    ("manager", "Супер, зафиксировала «Соколова» для нанесения на кофту"),
    ("client", "Казань"),
    ("manager", "Казань - отлично. Какой дизайн хотите нанести на кофту?"),
    ("client", "чёрный"),
    ("manager", "Чёрный цвет зафиксировала. Какой дизайн нанесём на кофту?"),
    ("client", "рост 180 вес 60"),
    ("manager", "Рост и вес зафиксировала. Какой дизайн нанесём на чёрную кофту?"),
    ("client", "Соколова Ирина Петровна, 89001234567"),
]


class TestCollectSlots:
    def test_dialog_52_fully_recovered(self):
        slots = collect_slots(DIALOG_52)
        assert slots == {
            "inscription": "Соколова",
            "city": "Казань",
            "color": "чёрный",
            "size": "рост 180 см, вес 60 кг",
            "recipient": "Соколова Ирина Петровна",
            "phone": "89001234567",
        }

    def test_empty_history(self):
        assert collect_slots([]) == {}
        assert format_slots_block({}) == ""

    def test_manager_words_are_not_client_facts(self):
        """Город из НАШЕЙ реплики не считается — это предложение, а не ответ."""
        assert "city" not in collect_slots([("manager", "Доставка в Казань?")])

    def test_client_can_change_his_mind(self):
        """Диалог 51: свитшот → «я хочу толстовку». Побеждает последнее слово."""
        slots = collect_slots([("client", "свитшот"), ("client", "я хочу толстовку")])
        assert slots["product"] == "толстовк"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("рост 180 вес 60", "рост 180 см, вес 60 кг"),
            ("180 и 60", "рост 180 см, вес 60 кг"),
            ("100 179", "рост 179 см, вес 100 кг"),
        ],
    )
    def test_size_formats(self, text, expected):
        """Диалог 37: «100 179» — модель прочла только рост и переспросила вес."""
        assert collect_slots([("client", text)])["size"] == expected

    def test_price_is_not_a_size(self):
        assert "size" not in collect_slots([("client", "4990 рублей это дорого")])

    def test_inscription_only_after_our_question(self):
        """Без нашего вопроса «Соколова» — это фамилия клиента, а не надпись."""
        assert "inscription" not in collect_slots([("client", "Соколова")])

    def test_long_answer_is_not_an_inscription(self):
        """Развёрнутая реплика может содержать встречный вопрос — не засчитываем."""
        history = [
            ("manager", "Какое имя или фамилию напишем на Вашей кофте?"),
            ("client", "а можно сначала узнать сколько это будет стоить вообще"),
        ]
        assert "inscription" not in collect_slots(history)

    def test_two_word_city_wins_over_substring(self):
        assert collect_slots([("client", "Нижний Новгород")])["city"] == "Нижний новгород"


class TestSlotsBlock:
    def test_block_lists_facts_in_funnel_order(self):
        block = format_slots_block(collect_slots(DIALOG_52))
        assert "НЕ переспрашивай" in block
        assert block.index("надпись") < block.index("город") < block.index("цвет")


class TestCityQuestion:
    @pytest.mark.parametrize(
        "text",
        [
            "В какой город нужна будет доставка?",
            "Подскажите, в какой город нужна доставка?",
            "Уточните город доставки",
        ],
    )
    def test_delivery_script_recognised(self, text):
        assert ASKS_CITY_RE.search(text)

    def test_unrelated_script_not_matched(self):
        assert not ASKS_CITY_RE.search("Какой цвет свитшота выберем?")
