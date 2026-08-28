"""Deterministic product-price gate for ping-funnel discovery."""

import pytest

from app.ping.agent import _manager_sent_price


@pytest.mark.parametrize(
    "price",
    [
        "5490р",
        "8.980р",
        "5 990 ₽",
        "12\u00a0980 руб",
        "12900 рублей",
    ],
)
def test_product_price_formats_used_in_scripts_are_recognized(price):
    history = f"[ИИ] Стоимость изделия сегодня {price}\n[ИИ] В какой город доставка?"
    assert _manager_sent_price(history) is True


@pytest.mark.parametrize("amount", ["890р", "800 руб", "350 ₽"])
def test_three_digit_delivery_or_deposit_is_not_product_price(amount):
    assert _manager_sent_price(f"[ИИ] Доставка от {amount}") is False


def test_price_written_only_by_client_does_not_open_ping_funnel():
    assert _manager_sent_price("[Клиент] У вас комплект 8.980р?") is False
