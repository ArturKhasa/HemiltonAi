"""Гигиена одного хода: не спрашивать дважды и не называть две цены.

Клиент 44731492 за один ход получил «В какой город нужна доставка?» трижды и два
разных расчёта — 5 990 ₽ и 4 990 ₽ (диалог 111, 07:37-07:38).
"""
from app.ai.runner import ReplyPart, _drop_repeated_questions


def FakePart(text, image_urls=None):
    """Настоящая часть хода без строки в базе: гейты правят и то, и другое."""
    return ReplyPart(text=text, image_urls=image_urls or [], message=None)


def _texts(parts):
    return [p.text for p in parts]


class TestDropRepeatedQuestions:
    def test_same_question_in_the_next_part_is_removed(self):
        parts = [
            FakePart("Стоимость 4 990 ₽\n\nВ какой город нужна доставка?"),
            FakePart("Шьём по вашим меркам.\n\nВ какой город нужна доставка?"),
        ]
        got = _texts(_drop_repeated_questions(parts, "ctx"))
        assert got[0].endswith("В какой город нужна доставка?")
        assert got[1] == "Шьём по вашим меркам."

    def test_part_left_empty_is_dropped(self):
        parts = [FakePart("В какой город нужна доставка?"), FakePart("В какой город нужна доставка?")]
        assert len(_drop_repeated_questions(parts, "ctx")) == 1

    def test_part_with_only_a_photo_survives(self):
        parts = [
            FakePart("Какой цвет выберем?"),
            FakePart("Какой цвет выберем?", image_urls=["https://example.ru/a.jpg"]),
        ]
        got = _drop_repeated_questions(parts, "ctx")
        assert len(got) == 2 and got[1].text == ""

    def test_different_questions_both_stay(self):
        parts = [FakePart("Какой цвет выберем?"), FakePart("А рост и вес подскажете?")]
        assert len(_drop_repeated_questions(parts, "ctx")) == 2

    def test_wording_differences_are_not_a_repeat(self):
        """Снимаем только дословный повтор: перефразированный вопрос — новый шаг."""
        parts = [
            FakePart("В какой город нужна доставка?"),
            FakePart("Подскажите город и адрес пункта выдачи?"),
        ]
        assert len(_drop_repeated_questions(parts, "ctx")) == 2

    def test_punctuation_and_case_do_not_hide_a_repeat(self):
        parts = [FakePart("В какой город нужна доставка?"), FakePart("в какой город нужна доставка ?")]
        assert len(_drop_repeated_questions(parts, "ctx")) == 1
