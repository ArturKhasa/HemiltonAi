"""Гейты воронки должны срабатывать на том статусе, который стоит в проде.

Три защиты в runner сравнивались с литералом «Горячий клиент». В проде статус
называется «Горячий» (id 3), а «Горячий клиент» (id 9) — пустой дубль, который
никто не ставит. Из-за этого гейты не сработали ни разу: статус ездил назад
(«Горячий» → «Есть расчет» → «Горячий», диалог 142), «Ждем предоплату» не
ставился никогда, а раз он не ставился — не переключалась и воронка пингов,
и клиент, уже выбравший способ оплаты, получал холодный пинг «что для Вас
важнее, качество или цена?» (диалог 150, 10:15).
"""
import pytest

from app.sales.status_names import (
    AWAITING_PREPAY,
    CALCULATED,
    HOT_ALLOWED_NEXT,
    INTERESTED,
    can_await_prepay,
    is_hot,
)


class TestHot:
    @pytest.mark.parametrize("name", ["Горячий", "Горячий клиент"])
    def test_both_production_spellings_count_as_hot(self, name):
        assert is_hot(name)

    @pytest.mark.parametrize("name", [INTERESTED, CALCULATED, None, "Спам"])
    def test_other_statuses_are_not_hot(self, name):
        assert not is_hot(name)

    def test_hot_may_only_go_to_prepayment(self):
        assert AWAITING_PREPAY in HOT_ALLOWED_NEXT
        # Откат назад запрещён — именно он и происходил в диалоге 142.
        assert CALCULATED not in HOT_ALLOWED_NEXT
        assert INTERESTED not in HOT_ALLOWED_NEXT


class TestPrepaymentGate:
    @pytest.mark.parametrize(
        "name", ["Горячий", "Горячий клиент", CALCULATED, AWAITING_PREPAY, "Заказ оформлен"],
    )
    def test_advanced_statuses_may_reach_prepayment(self, name):
        assert can_await_prepay(name)

    @pytest.mark.parametrize("name", [INTERESTED, None, "Нужен куратор"])
    def test_early_statuses_may_not(self, name):
        """Иначе предоплату просят на первом же сообщении (клиент 8465497)."""
        assert not can_await_prepay(name)
