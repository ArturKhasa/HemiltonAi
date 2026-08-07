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
