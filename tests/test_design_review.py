"""Сверка дизайна уходит раскладкой из скрипта, а не пересказом модели.

Диалог 89, 11:24: вместо «На груди слева - герб РФ / На груди по центру -
надпись … / На рукаве справа - флаг РФ / На спине - герб РФ» клиент прочитал
«Элементы дизайна - только надпись «Орех», расположение не уточнено» — мест
нанесения в сообщении не осталось вовсе.
"""
import pytest

from app.sales.funnel_steps import render_design_inscription, render_design_review

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


class TestRenderDesignReview:
    """Раскладка в скрипте — пример патриотической линейки. Клиенту, заказавшему
    одну надпись «Чебурек», в сверку пришли ещё герб на груди, флаг на рукаве и
    герб на спине, которых он не просил (диалог 90, 11:53)."""

    def test_only_the_inscription_survives(self):
        got = render_design_review(SCRIPT, "Чебурек", ["Свитшот", "Черный", "170 70"])
        assert got == (
            "Зафиксировала размер! Теперь давайте согласуем дизайн:\n\n"
            "На груди по центру - надпись «Чебурек»\n\n"
            "Всё верно?)"
        )

    def test_requested_emblem_is_kept(self):
        got = render_design_review(
            SCRIPT, "Чебурек", ["хочу герб на груди", "170 70"],
        )
        assert "На груди слева - герб РФ" in got
        assert "На спине - герб РФ" in got
        assert "флаг" not in got

    def test_requested_flag_is_kept(self):
        got = render_design_review(SCRIPT, "Чебурек", ["и флаг на рукав добавьте"])
        assert "На рукаве справа - флаг РФ" in got
        assert "герб" not in got

    def test_full_patriotic_order_keeps_everything(self):
        got = render_design_review(SCRIPT, "РОССИЯ", ["хочу герб и флаг, как на фото"])
        for line in ("герб РФ", "флаг РФ", "надпись «РОССИЯ»"):
            assert line in got

    def test_no_inscription_drops_the_inscription_line(self):
        got = render_design_review(SCRIPT, None, ["давайте герб"])
        assert "надпись" not in got
        assert "На груди слева - герб РФ" in got

    def test_nothing_requested_gives_none(self):
        """Согласовывать нечего — шаг ведёт модель, ей есть что спросить."""
        assert render_design_review(SCRIPT, None, ["Свитшот", "170 70"]) is None

    def test_intro_and_question_survive_the_filter(self):
        got = render_design_review(SCRIPT, "Чебурек", [])
        assert got.startswith("Зафиксировала размер!")
        assert got.endswith("Всё верно?)")
