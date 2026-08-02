"""Сверка дизайна уходит раскладкой из скрипта, а не пересказом модели.

Диалог 89, 11:24: вместо «На груди слева - герб РФ / На груди по центру -
надпись … / На рукаве справа - флаг РФ / На спине - герб РФ» клиент прочитал
«Элементы дизайна - только надпись «Орех», расположение не уточнено» — мест
нанесения в сообщении не осталось вовсе.
"""
import pytest

from app.sales.funnel_steps import render_design_inscription

SCRIPT = (
    "Зафиксировала размер! Теперь давайте согласуем дизайн:\n\n"
    "На груди слева - герб РФ\n"
    'На груди по центру - надпись "РОССИЯ"\n'
    "На рукаве справа - флаг РФ\n"
    "На спине - герб РФ +\n\n\n"
    "Всё верно?)"
)


class TestRenderDesignInscription:
    def test_client_inscription_replaces_the_example(self):
        got = render_design_inscription(SCRIPT, "Орех")
        assert "На груди по центру - надпись «Орех»" in got
        assert "РОССИЯ" not in got

    def test_the_rest_of_the_layout_survives(self):
        got = render_design_inscription(SCRIPT, "Орех")
        for line in ("На груди слева - герб РФ", "На рукаве справа - флаг РФ",
                     "На спине - герб РФ +", "Всё верно?)"):
            assert line in got

    def test_only_the_first_inscription_line_is_touched(self):
        text = 'надпись "РОССИЯ"\nи ещё надпись "РОССИЯ"'
        got = render_design_inscription(text, "Орех")
        assert got == 'надпись «Орех»\nи ещё надпись "РОССИЯ"'

    @pytest.mark.parametrize("inscription", [None, ""])
    def test_no_inscription_keeps_the_script_as_is(self, inscription):
        assert render_design_inscription(SCRIPT, inscription) == SCRIPT

    def test_inscription_with_backslash_is_inserted_literally(self):
        got = render_design_inscription('надпись "РОССИЯ"', r"C\N")
        assert got == "надпись «C\\N»"
