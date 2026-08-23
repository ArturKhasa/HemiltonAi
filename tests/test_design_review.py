"""Сверка дизайна уходит раскладкой из скрипта, а не пересказом модели.

Диалог 89, 11:24: вместо «На груди слева - герб РФ / На груди по центру -
надпись … / На рукаве справа - флаг РФ / На спине - герб РФ» клиент прочитал
«Элементы дизайна - только надпись «Орех», расположение не уточнено» — мест
нанесения в сообщении не осталось вовсе.
"""
import pytest

from app.sales.funnel_steps import (
    render_design_inscription,
    render_design_placement,
    render_design_review,
)

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
            "На груди справа - надпись «Чебурек»\n\n"
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


class TestDesignPlacement:
    """Место нанесения по умолчанию. ОП, 22.08: «ИИ во всех диалогах прописывает
    имя спереди посередине, мы так не делаем. Если имя - то это по умолчанию на
    груди справа. Если фамилия - то это по умолчанию на спине с гербом»."""

    def test_name_goes_to_the_right_of_the_chest(self):
        got = render_design_review(SCRIPT, "Андрей", ["170 70"])
        assert "На груди справа - надпись «Андрей»" in got
        assert "по центру" not in got

    def test_surname_goes_to_the_back_with_the_emblem(self):
        got = render_design_review(SCRIPT, "Соколов", ["170 70"])
        assert "На спине - герб РФ и надпись «Соколов»" in got
        assert "по центру" not in got

    def test_pair_order_with_a_surname_goes_to_the_back(self):
        got = render_design_review(SCRIPT, "Шишкин Кирилл", ["170 70"])
        assert "На спине - герб РФ и надпись «Шишкин Кирилл»" in got

    def test_name_that_ends_like_a_surname_stays_a_name(self):
        got = render_design_review(SCRIPT, "Ирина", ["170 70"])
        assert "На груди справа - надпись «Ирина»" in got

    def test_client_placement_beats_the_default(self):
        """«по центру не нужно. Лучше слева и небольшими буквами» — отрицание
        относится к центру, а место берём то, которое клиент назвал вторым."""
        got = render_design_review(
            SCRIPT, "Андрей", ["по центру не нужно. Лучше слева и небольшими буквами"],
        )
        assert "На груди слева - надпись «Андрей»" in got
        assert "по центру" not in got

    def test_client_asks_for_the_back(self):
        got = render_design_review(SCRIPT, "Андрей", ["давайте на спине"])
        assert "На спине - надпись «Андрей»" in got
        assert "герб" not in got

    def test_emblem_asked_by_the_client_is_not_duplicated(self):
        """Герб клиент назвал сам — он уже стоит строкой раскладки."""
        got = render_design_review(SCRIPT, "Соколов", ["хочу герб на спине"])
        assert "На спине - надпись «Соколов»" in got
        assert got.count("герб РФ и надпись") == 0
        assert "На спине - герб РФ" in got

    def test_placement_of_the_emblem_is_not_taken_for_the_inscription(self):
        """«герб на спине» — это про герб, надпись остаётся на груди."""
        got = render_design_review(SCRIPT, "Андрей", ["хочу герб на спине"])
        assert "На груди справа - надпись «Андрей»" in got

    def test_line_without_a_placement_gets_one(self):
        got = render_design_placement('надпись «Андрей»', "Андрей", [])
        assert got == "На груди справа - надпись «Андрей»"

    def test_no_inscription_leaves_the_text_alone(self):
        assert render_design_placement(SCRIPT, None, []) == SCRIPT


TEMPLATE = (
    "Зафиксировала размер! Теперь давайте согласуем дизайн:\n\n"
    "[раскладка]\n\n"
    "Всё верно?)"
)


class TestDesignLayoutTemplate:
    """Раскладку собирает система, формулировки вокруг остаются за панелью.

    Формат взят у менеджеров (боевые диалоги 183 и 409, 20.08): имя справа на
    груди, фамилия на спине с гербом в центре. Скрипт был записан иначе — «На
    груди по центру - надпись "РОССИЯ"», — и с 21.08 по 22.08 двенадцать клиентов
    получили сверку с именем посреди груди.
    """

    def test_name_goes_to_the_right_of_the_chest(self):
        got = render_design_review(TEMPLATE, "Андрей", ["белый свитшот"])
        assert got == (
            "Зафиксировала размер! Теперь давайте согласуем дизайн:\n\n"
            "НА ГРУДИ\n- Справа: Андрей\n\n"
            "Всё верно?)"
        )

    def test_surname_goes_to_the_back_with_the_emblem(self):
        got = render_design_review(TEMPLATE, "Соколов", ["чёрный свитшот"])
        assert "НА СПИНЕ\n- Сверху: Соколов\n- В центре: Герб РФ" in got
        assert "НА ГРУДИ" not in got

    def test_name_and_surname_split_between_chest_and_back(self):
        got = render_design_review(TEMPLATE, "Артур Халитов", ["170 70"])
        assert "НА ГРУДИ\n- Справа: Артур" in got
        assert "НА СПИНЕ\n- Сверху: Халитов" in got

    def test_client_placement_beats_the_default(self):
        got = render_design_review(
            TEMPLATE, "Андрей", ["по центру не нужно. Лучше слева и небольшими буквами"],
        )
        assert "НА ГРУДИ\n- Слева: Андрей" in got
        assert "Справа" not in got

    def test_only_what_the_client_named_gets_in(self):
        got = render_design_review(TEMPLATE, "Чебурек", ["Свитшот", "Черный", "170 70"])
        assert "флаг" not in got.lower()
        assert "герб" not in got.lower()

    def test_flag_goes_to_the_sleeve_when_asked(self):
        got = render_design_review(TEMPLATE, "Соколов", ["и флаг на рукав добавьте"])
        assert "На правом рукаве: Флаг РФ" in got

    def test_emblem_on_the_chest_when_there_is_no_surname(self):
        got = render_design_review(TEMPLATE, "Чебурек", ["хочу герб на груди"])
        assert "НА ГРУДИ\n- Справа: Чебурек\n- Слева: Герб РФ" in got

    def test_nothing_to_agree_gives_none(self):
        assert render_design_review(TEMPLATE, None, ["Свитшот", "170 70"]) is None

    def test_wording_around_the_layout_survives(self):
        """Панель правит текст вокруг плейсхолдера — код его не трогает."""
        custom = "Собрала Ваш дизайн ❤\n\n[раскладка]\n\nВсё так?"
        got = render_design_review(custom, "Андрей", [])
        assert got.startswith("Собрала Ваш дизайн ❤")
        assert got.endswith("Всё так?")

    def test_inscription_with_backslash_is_inserted_literally(self):
        got = render_design_review(TEMPLATE, r"C\N", [])
        assert "- Справа: C\\N" in got
