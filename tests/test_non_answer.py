"""Переспрос — не ответ.

Диалог 756, 20 августа: на «какое имя напишем на кофте?» клиент написал «М?»,
получил «Супер, зафиксировала» и следом прайс; на «Чего?» — снова
«Супер, зафиксировала!». Через минуту спросил, бот с ним говорит или человек.
"""
import pytest

from app.sales.non_answer import is_non_answer


class TestConfused:
    @pytest.mark.parametrize("text", [
        "М?", "Чего?", "Что?", "че", "?", "??", "...", "а?", "Ну",
        "не понял", "Не поняла", "в смысле", "О чём вы", "непонятно",
    ])
    def test_reask_is_not_an_answer(self, text):
        assert is_non_answer(text) is True


class TestRealAnswers:
    @pytest.mark.parametrize("text", [
        "Вова Чудаев", "Чёрный", "Давайте", "66 рост 176", "Екатеринбург",
        "Шаманский", "да", "нет", "Как оплатить?", "что по цене?",
        "Хочу посмотреть примеры работ",
    ])
    def test_answer_passes(self, text):
        assert is_non_answer(text) is False

    def test_attachment_is_not_a_reask(self):
        """Фото клиент прислал осмысленно — переспрашивать не нужно."""
        assert is_non_answer("[фото]") is False
        assert is_non_answer("[голосовое сообщение]") is False

    def test_empty_text_is_not_a_reask(self):
        assert is_non_answer("") is False
        assert is_non_answer("   ") is False
