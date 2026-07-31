"""Как обращаемся к клиенту.

Правила ОП: уменьшительные разворачиваем в полные, латиница и псевдонимы — просто
«Вы», по фамилии не обращаемся никогда. Последнее легко нарушить: на вопрос «какое
имя или фамилию напишем на кофте?» клиент отвечает фамилией, и она попадает в
обращение — «Иванова, здравствуйте» звучит как повестка.
"""
import pytest

from app.utils.text import render_name_placeholder, usable_name

PHRASE = "[Имя], какое имя или фамилию напишем на Вашей кофте?"
NO_NAME = "Какое имя или фамилию напишем на Вашей кофте?"


class TestDiminutives:
    @pytest.mark.parametrize(
        "short,full",
        [("Женя", "Евгений"), ("Саша", "Александр"), ("Катя", "Екатерина"),
         ("Маша", "Мария"), ("Лёша", "Алексей"), ("Настя", "Анастасия"),
         ("женя", "Евгений")],
    )
    def test_expanded_to_full(self, short, full):
        assert usable_name(short) == full


class TestSurnames:
    @pytest.mark.parametrize(
        "surname",
        ["Иванова", "Иванов", "Петров", "Зайцева", "Смирнов", "Кузнецова",
         "Достоевский", "Крупская", "Шевченко", "Петренко", "Мкртчян", "Гвиниашвили"],
    )
    def test_never_used_as_address(self, surname):
        assert usable_name(surname) is None

    def test_dropped_from_script_text(self):
        assert render_name_placeholder(PHRASE, "Иванова") == NO_NAME

    @pytest.mark.parametrize("name", ["Дима", "Ксюша", "Соня", "Настя"])
    def test_diminutive_wins_over_surname_ending(self, name):
        """«Дима» кончается на «а», «Ксюша» — на «ша»: словарь проверяется первым."""
        assert usable_name(name) is not None

    @pytest.mark.parametrize(
        "name",
        ["Ирина", "Марина", "Алина", "Полина", "Кристина", "Екатерина",
         "Валентина", "Галина", "Ангелина", "Карина", "Регина", "Константин"],
    )
    def test_names_ending_like_surnames_survive(self, name):
        """Живые имена на -ина/-ин. Без белого списка фильтр съедал их все, и
        заметная доля клиенток слышала безличное «Вы» вместо имени."""
        assert usable_name(name) == name

    @pytest.mark.parametrize("name", ["Ева", "Лев", "Нина", "Дина", "Инна"])
    def test_short_names_not_suffix_matched(self, name):
        """Короче пяти букв — фамилией быть не может, окончание не смотрим."""
        assert usable_name(name) == name


class TestNonNames:
    @pytest.mark.parametrize(
        "raw",
        ["Max", "Sasha", "Anna", "ivan", "🙂", "xxx123", "", "   ", None,
         "Ночной Волк", "user1234"],
    )
    def test_addressed_without_name(self, raw):
        assert usable_name(raw) is None
        assert render_name_placeholder(PHRASE, raw) == NO_NAME


class TestOrdinaryNames:
    @pytest.mark.parametrize("name", ["Елена", "Ольга", "Иван", "Пётр", "Анна-Мария"])
    def test_kept_as_is(self, name):
        assert usable_name(name) == name

    def test_lowercase_capitalised(self):
        assert usable_name("елена") == "Елена"

    def test_substituted_into_script(self):
        assert render_name_placeholder(PHRASE, "Елена").startswith("Елена, какое имя")
