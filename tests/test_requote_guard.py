"""Повторный прайс в ответ на возражение.

Клиент отвечает «цена» на вопрос «что остановило — цена или сроки?», а бот
присылает стоимость заново. Правило в промпте это не удерживало.
"""
import pytest

from app.ai.runner import _requotes_known_price

SENT = ["Свитшот с термопринтом сегодня 4 990 ₽. В какой город доставка?"]


@pytest.mark.parametrize("answer", ["цена", "Цена", " цена ", "дорого", "сроки", "не надо"])
def test_repeated_price_caught(answer):
    assert _requotes_known_price(answer, "Цена свитшота сегодня - 4 990 ₽.", SENT) is True


def test_same_sum_written_differently():
    assert _requotes_known_price("цена", "Стоимость 4990руб", SENT) is True


class TestNoFalsePositives:
    def test_objection_handled_without_price(self):
        assert _requotes_known_price(
            "цена", "Понимаю. Можно оформить оплату частями - рассмотрите?", SENT) is False

    def test_direct_price_question_allowed(self):
        """«сколько стоит?» — это вопрос, а не ответ на возражение."""
        assert _requotes_known_price(
            "а сколько стоит?", "Свитшот 4 990 ₽", SENT) is False

    def test_new_price_allowed(self):
        """Цена другого товара — не повтор."""
        assert _requotes_known_price("цена", "Лонгслив 2 790 ₽", SENT) is False

    def test_first_price_in_dialog(self):
        assert _requotes_known_price("цена", "Свитшот 4 990 ₽", []) is False
