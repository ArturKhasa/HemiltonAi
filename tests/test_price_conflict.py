"""Две разные суммы за один заказ в одном ходу клиенту не уходят.

Клиент 44731492 получил подряд «5 990 ₽ (вместо 7 380 ₽)» и «4 990 ₽ (вместо
5 990 ₽)»: на стадии pricing девять активных скриптов с одним условием и разными
числами, и связка со скриптом модели разошлись (диалог 111, 07:37-07:38).
"""
from dataclasses import dataclass

from app.ai.runner import _drop_conflicting_prices


@dataclass
class FakePart:
    text: str


def _texts(parts):
    return [p.text for p in parts]


class TestDropConflictingPrices:
    def test_second_price_is_dropped(self):
        parts = [FakePart("Стоимость - 5 990 ₽"), FakePart("Стоимость - 4 990 ₽")]
        assert _texts(_drop_conflicting_prices(parts, [], "ctx")) == ["Стоимость - 5 990 ₽"]

    def test_price_conflicting_with_history_is_dropped(self):
        parts = [FakePart("Получается сумма заказа - 4 990 ₽")]
        assert _drop_conflicting_prices(parts, ["Стоимость толстовки - 5 990 руб"], "ctx") == []

    def test_same_price_again_is_fine(self):
        """Повтор суммы — нормально: итог заказа называют ещё раз при оформлении."""
        parts = [FakePart("Итого 5 990 ₽, оплата частями")]
        assert len(_drop_conflicting_prices(parts, ["Стоимость - 5 990 ₽"], "ctx")) == 1

    def test_old_and_new_price_in_one_message_is_one_offer(self):
        parts = [FakePart("СЕГОДНЯ - 5 990 ₽ (вместо 7 380 ₽)")]
        assert len(_drop_conflicting_prices(parts, [], "ctx")) == 1

    def test_replies_without_prices_pass_through(self):
        parts = [FakePart("А цвет какой выберем?"), FakePart("Рост и вес подскажете?")]
        assert len(_drop_conflicting_prices(parts, ["Стоимость - 5 990 ₽"], "ctx")) == 2


class TestPricesWrittenByHand:
    """ОП пишет цены в скрипты руками и по-своему.

    Расчёт комплекта (скрипт 519) — «8.980р (вместо 12.980р)»: точка разделителем
    тысяч и одна буква «р». Такую сумму шаблон не видел вовсе, и проверки цены
    считали, что клиенту ничего не называли.
    """

    KOMBO = (
        "Расскажу по цене:\n"
        "- Толстовка (хлопок 85%) - 5490р\n"
        "- Демисезонная жилетка непромокаемая - 3490р\n\n"
        "Комплект из двух изделий со скидкой - 8.980р (вместо 12.980р)"
    )

    def test_hand_written_sums_are_seen(self):
        from app.ai.runner import _prices_in

        assert _prices_in(self.KOMBO) == {"5490", "3490", "8980", "12980"}

    def test_single_price_does_not_follow_the_set(self):
        """За расчётом комплекта уходила сумма заказа на одно изделие."""
        parts = [FakePart("Получается сумма заказа - 5 990 ₽")]

        assert _drop_conflicting_prices(parts, [self.KOMBO], "ctx") == []

    def test_the_set_price_itself_passes(self):
        parts = [FakePart("Получается сумма заказа - 8 980 ₽")]

        assert len(_drop_conflicting_prices(parts, [self.KOMBO], "ctx")) == 1

    def test_percentages_and_measurements_are_not_money(self):
        from app.ai.runner import _prices_in

        assert _prices_in("вискоза/хлопок - 85%, лайкра - 15%") == set()
        assert _prices_in("Рост 183 см, вес 93 кг") == set()
