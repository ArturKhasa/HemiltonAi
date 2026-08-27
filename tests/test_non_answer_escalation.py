"""Вопрос вместо имени отдаём менеджеру.

Мой вопрос Лене 26.08: «что делаем, когда клиент не отвечает на "какое имя или
фамилию напишем на Вашей кофте?" — могут ответить вопросом на вопрос, могут
написать какую-то ерунду». Ответ: «Если вопросом на вопрос, то лучше адресовать
менеджеру, потому что таких диалогов почти нет, а если есть это чет неадекватное
скорее всего. Цензуры в целом нет, с матами тоже делали дизайны».

Отделить встречный вопрос от согласия обязательно. «+» — кодовое слово из
рекламы («кодовые слова: начать, +, /start»), и в ответах на вопрос про надпись
за две недели их 59 из 62. Считать их встречным вопросом значит завалить
менеджеров работой там, где клиент просто соглашается.

Порог заказчик уточнил 27.08: на вопрос про имя — ЛЮБОЙ вопрос вместо ответа
зовёт менеджера, включая «Какая цена?». Правило от 21.08 («спросил про цену —
отправь цену») от этого не ломается: реплику клиент получает, диалог встаёт на
паузу уже после неё.

Замеры по боевой базе за две недели: вопрос вместо имени — 71 диалог из 3 225,
встречный вопрос на любом другом нашем вопросе — ещё 22.
"""
import pytest

from app.sales.non_answer import is_counter_question, is_non_answer


class TestCounterQuestion:
    @pytest.mark.parametrize("text", ["?", "???", ")?", "Чего?", "Что?", "М?", "Не понял", "м", "Ну"])
    def test_confusion_and_bare_question_marks(self, text):
        assert is_counter_question(text) is True

    @pytest.mark.parametrize("text", ["+", '"+"', "👍", "🤝", ".", "..."])
    def test_agreement_is_not_a_counter_question(self, text):
        """«+» держит воронку (отвечать на вопрос про надпись он не отвечает),
        но человека не зовёт: клиент соглашается, а не спрашивает."""
        assert is_counter_question(text) is False
        # При этом ответом он по-прежнему не считается — воронка стоит.
        if text not in ("👍", "🤝"):
            assert is_non_answer(text) is True

    @pytest.mark.parametrize("text", [
        "а сколько стоит?",
        "Смирнов",
        "Киркоров",
        "можно два изделия?",
    ])
    def test_business_questions_and_answers_pass_through(self, text):
        """Вопрос по делу отрабатывают скрипты: правило Лены от 21.08 требует
        отправить на него цену, а не звать человека. «Ерунда» — это надпись:
        цензуры нет, дизайны делали и с матами."""
        assert is_counter_question(text) is False

    def test_attachment_only_is_not_a_counter_question(self):
        assert is_counter_question("[фото]") is False

    def test_empty(self):
        assert is_counter_question("") is False
        assert is_counter_question(None) is False


class TestScope:
    """Что именно зовёт менеджера — проверяем на текстах из боевой базы."""

    ASKS_NAME = "Какое имя или фамилию напишем на Вашей кофте?"
    ASKS_CITY = "В какой город нужна будет доставка?"

    @staticmethod
    def _escalates(our_last: str, client_text: str) -> bool:
        """Условие из runner, слово в слово."""
        from app.sales.order_slots import ASKS_INSCRIPTION_RE

        if ASKS_INSCRIPTION_RE.search(our_last):
            if "?" in client_text or is_counter_question(client_text):
                return True
        return "?" in our_last and is_counter_question(client_text)

    @pytest.mark.parametrize("text", [
        "Какая цена?", "Цена?", "Сколько стоит?", "А можно без фамилии и имени ?",
        "Башкирский герб можно?", "А можно просто Россия?", "?", "Чего?",
    ])
    def test_any_question_instead_of_the_name(self, text):
        assert self._escalates(self.ASKS_NAME, text) is True

    @pytest.mark.parametrize("text", ["+", "Смирнов", "Киркоров", "👍"])
    def test_an_answer_to_the_name_question_does_not(self, text):
        assert self._escalates(self.ASKS_NAME, text) is False

    def test_business_question_elsewhere_goes_to_the_scripts(self):
        """В середине воронки вопрос по делу отрабатывают скрипты."""
        assert self._escalates(self.ASKS_CITY, "а сколько стоит доставка?") is False

    def test_counter_question_elsewhere_calls_the_manager(self):
        assert self._escalates(self.ASKS_CITY, "?") is True
        assert self._escalates(self.ASKS_CITY, "Не понял") is True

    def test_our_statement_without_a_question_never_escalates(self):
        assert self._escalates("Передала заказ в работу.", "?") is False
