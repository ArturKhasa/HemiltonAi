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


class TestInscriptionVocative:
    """Надпись на изделии как обращение — не только в начале реплики.

    «Отлично, в Ваш город доставляем СДЭК... \n\nОрех, а цвет для свитшота какой
    выберем?»: начало занято текстом скрипта, и первое слово проверять поздно.
    """

    def test_after_blank_line(self):
        got = strip_foreign_name(
            "Оплата доставки при получении.\n\nОрех, а цвет какой выберем?",
            None, "Орех",
        )
        assert got == "Оплата доставки при получении.\n\nА цвет какой выберем?"

    def test_mid_sentence_start(self):
        got = strip_foreign_name("Всё записала. Орех, а размер?", None, "Орех")
        assert got == "Всё записала. А размер?"

    def test_at_the_very_start_too(self):
        assert strip_foreign_name("Орех, а размер?", None, "Орех") == "А размер?"

    def test_inscription_equal_to_own_name_is_kept(self):
        text = "Всё записала. Ирина, а размер?"
        assert strip_foreign_name(text, "Ирина", "Ирина") == text

    def test_inscription_elsewhere_in_text_untouched(self):
        text = "Наносим надпись «Орех» на спину. Какой цвет ниток?"
        assert strip_foreign_name(text, None, "Орех") == text

    @pytest.mark.parametrize("inscription", [None, "", "Хемильтон 2026", "Я"])
    def test_no_single_word_inscription_no_change(self, inscription):
        text = "Доставим СДЭК.\n\nОрех, а цвет какой?"
        assert strip_foreign_name(text, "Ирина", inscription) == text

    def test_enumeration_is_not_a_vocative(self):
        """Слово из перечисления совпадать с надписью не может, а строка с ним
        начинается ровно так же — проверяем, что чужие слова не трогаем."""
        text = "Есть варианты.\nБелый, бежевый, серый - какой ближе?"
        assert strip_foreign_name(text, None, "Орех") == text
