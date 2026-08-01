"""Плейсхолдеры CRM в текстах скриптов ОП.

CRM отключили, подставлять их стало нечем — и клиент получал «Номер Вашего
заказа: [Заказ.Номер]» вместе с «[Корзина]», «[Доставка.ФИО]» и «[Доставка.
Телефон]» (диалог 68, сообщения 964 и 978).
"""
from app.sales.order_slots import collect_slots, render_order_placeholders

SUMMARY = """Давайте с Вами подытожим и проверим Ваш заказ:

Номер Вашего заказа: [Заказ.Номер]

Итог:
[Корзина]

1. Дизайн:
[Заказ.Примечания (внутренние)]

2. Размер:
[Заказ.Рост]
[Заказ.Вес]

3. ФИО и телефон
[Доставка.ФИО]
[Доставка.Телефон]

Все ли правильно по заказу?"""

SLOTS = {
    "inscription": "Соколова",
    "product": "свитшот",
    "color": "чёрный",
    "height": "180",
    "weight": "60",
    "recipient": "Петров Петр Петрович",
    "phone": "79812734578",
}


class TestRenderOrderPlaceholders:
    def test_known_fields_substituted(self):
        result = render_order_placeholders(SUMMARY, SLOTS)
        assert "Петров Петр Петрович" in result
        assert "79812734578" in result
        assert "рост 180 см" in result and "вес 60 кг" in result
        assert "надпись «Соколова»" in result
        assert "свитшот, чёрный" in result

    def test_no_placeholder_survives(self):
        result = render_order_placeholders(SUMMARY, SLOTS)
        assert "[Заказ." not in result
        assert "[Доставка." not in result
        assert "[Корзина]" not in result

    def test_unfillable_line_is_dropped_whole(self):
        """Номер заказа выдаёт учётная система, которой у нас нет. Строка
        «Номер Вашего заказа:» без номера бессмысленна."""
        result = render_order_placeholders(SUMMARY, SLOTS)
        assert "Номер Вашего заказа" not in result
        assert "Давайте с Вами подытожим" in result
        assert "Все ли правильно по заказу?" in result

    def test_missing_slot_drops_only_its_line(self):
        result = render_order_placeholders(SUMMARY, {"recipient": "Петров Петр Петрович"})
        assert "Петров Петр Петрович" in result
        assert "2. Размер:" in result  # заголовок остаётся
        assert "[Заказ.Рост]" not in result

    def test_only_the_offending_sentence_is_cut(self):
        """Скрипт «6. Уточняем СДЭК»: благодарность и номер заказа в одной строке.
        Терять благодарность за оплаченный заказ из-за отсутствия номера нельзя."""
        text = "Благодарю Вас за заказ и за доверие! Номер Вашего заказа: [Заказ.Номер]"
        result = render_order_placeholders(text, SLOTS)
        assert result == "Благодарю Вас за заказ и за доверие!"

    def test_text_without_placeholders_untouched(self):
        text = "Отлично, тогда подскажите ФИО и номер телефона получателя"
        assert render_order_placeholders(text, SLOTS) == text

    def test_no_runs_of_blank_lines_left(self):
        result = render_order_placeholders(SUMMARY, {})
        assert "\n\n\n" not in result

    def test_cart_falls_back_to_default_product(self):
        """Изделие по умолчанию — свитшот, даже если клиент его не называл."""
        assert "свитшот" in render_order_placeholders("[Корзина]", {})


class TestSizeSlots:
    def test_height_and_weight_kept_separately(self):
        slots = collect_slots([("client", "рост 180 вес 60")])
        assert slots["height"] == "180"
        assert slots["weight"] == "60"
        assert slots["size"] == "рост 180 см, вес 60 кг"
