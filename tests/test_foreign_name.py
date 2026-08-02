"""Обращение по имени — только настоящим именем клиента.

Ответ на «какое имя или фамилию напишем на Вашей кофте?» — это надпись на
изделии. Клиент 289653120 (в профиле ВК имени нет вовсе) заказал кофту с
надписью «Иван» и получил «Иван, а цвет для свитшота какой выберем?», а пингом
— «Пётр» из соседнего заказа. Правило в промпте это не удерживает.
"""
import pytest

from app.utils.text import strip_foreign_name


class TestStripForeignName:
    def test_no_name_in_profile_drops_any_vocative(self):
        got = strip_foreign_name("Иван, а цвет для свитшота какой выберем?", None)
        assert got == "А цвет для свитшота какой выберем?"

    def test_wrong_name_dropped(self):
        got = strip_foreign_name("Пётр, толстовка стоит своих денег.", "Ирина")
        assert got == "Толстовка стоит своих денег."

    def test_real_name_kept(self):
        text = "Иван, а цвет какой выберем?"
        assert strip_foreign_name(text, "Иван") == text

    def test_diminutive_profile_name_matches_full_form(self):
        """usable_name разворачивает «Женя» в «Евгений» — обращение своё."""
        text = "Евгений, а цвет какой выберем?"
        assert strip_foreign_name(text, "Женя") == text

    def test_latin_profile_name_is_not_usable(self):
        """Латиницей не обращаемся, значит и вокатив в ответе чужой."""
        got = strip_foreign_name("Max, а цвет какой?", "Max")
        assert got == "А цвет какой?"

    @pytest.mark.parametrize("text", [
        "Отлично, тогда подскажите ФИО и телефон получателя",
        "Да, всё верно. Какой цвет выберем?",
        "Понимаю, цена может показаться выше.",
        "Здравствуйте! Меня зовут София.",
    ])
    def test_ordinary_openers_untouched(self, text):
        """«Отлично,» и «Понимаю,» — не имена, трогать их нельзя."""
        assert strip_foreign_name(text, None) == text

    def test_empty_rest_is_left_alone(self):
        assert strip_foreign_name("Иван, ", None) == "Иван, "

    def test_case_insensitive_match(self):
        text = "ИРИНА, добрый день"
        # Вокатив ловим только с заглавной первой и строчными дальше — «ИРИНА»
        # это не обращение, а часть надписи капсом.
        assert strip_foreign_name(text, "Ирина") == text
