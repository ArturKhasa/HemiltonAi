"""Подряд идущие реплики не должны открываться одним и тем же словом.

Диалог 85, 08:57-08:59: «Понимаю Ваши сомнения. При оплате всей суммы...»,
«Понимаю, не буду настаивать...», «Понимаю Ваши сомнения. Без предоплаты...» —
три реплики подряд с одного слова. Скрипты отработки возражений почти все
открываются «Понимаю», поэтому промпта тут мало.
"""
import pytest

from app.utils.text import vary_repeated_opening


class TestVaryRepeatedOpening:
    def test_first_use_is_untouched(self):
        text = "Понимаю, цена - важный момент."
        assert vary_repeated_opening(text, ["Свитшот или худи?"]) == text

    def test_second_понимаю_gets_another_opener(self):
        got = vary_repeated_opening(
            "Понимаю, не буду настаивать. Оставить заказ в силе?",
            ["Понимаю Ваши сомнения. При оплате всей суммы сразу - подарок."],
        )
        assert got == "Согласна, не буду настаивать. Оставить заказ в силе?"

    def test_verb_form_keeps_the_object(self):
        got = vary_repeated_opening(
            "Понимаю Ваши сомнения. Без предоплаты заказ не запустить.",
            ["Понимаю, цена - важный момент."],
        )
        assert got == "Прекрасно понимаю Ваши сомнения. Без предоплаты заказ не запустить."

    def test_third_in_a_row_avoids_both_previous_openers(self):
        got = vary_repeated_opening(
            "Понимаю Ваши сомнения. Все риски берём на себя.",
            [
                "Понимаю Ваши сомнения. При оплате всей суммы - подарок.",
                "Прекрасно понимаю, не буду настаивать.",
            ],
        )
        assert got.startswith("Слышу Ваши сомнения.")

    def test_older_messages_are_out_of_the_window(self):
        text = "Понимаю, цена - важный момент."
        history = ["Понимаю Ваши сомнения.", "Какой цвет выберем?", "Записала размер."]
        assert vary_repeated_opening(text, history) == text

    def test_unknown_opener_is_left_alone(self):
        text = "Записала размер, спасибо!"
        assert vary_repeated_opening(text, ["Записала цвет."]) == text

    def test_unsafe_continuation_is_left_alone(self):
        """«Понимаю, что...» заменить можно, «Понимаю сомнения» - уже нет:
        подстановка вводного слова сломает фразу, повтор её только повторит."""
        text = "Понимаю сомнения по срокам."
        assert vary_repeated_opening(text, ["Понимаю, цена - важный момент."]) == text

    @pytest.mark.parametrize("text", ["", "   ", "?"])
    def test_no_opener_no_crash(self, text):
        assert vary_repeated_opening(text, ["Понимаю, цена важна."]) == text

    def test_отлично_rotates_too(self):
        got = vary_repeated_opening(
            "Отлично, тогда подскажите ФИО и телефон получателя",
            ["Отлично, записала цвет!"],
        )
        assert got == "Супер, тогда подскажите ФИО и телефон получателя"
