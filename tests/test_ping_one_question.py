"""Один вопрос за пинг — то же правило ОП от 11.08, что и в ходах диалога.

В ходах его держит app.ai.runner._keep_one_question, а пинги шли мимо: за
06-08.09 на проде два вопроса были в 62 пингах из 4088 (1,5%) против 0,1% в
обычных ходах. Текст шага адаптирует модель, и она любит доклеить второй
вопрос — примеры ниже взяты из боевых сообщений тех суток.
"""
import pytest

from app.utils.text import keep_one_question, questions_in


class TestQuestionsIn:
    def test_counts_real_questions(self):
        text = "Вы выбираете для себя или в подарок? И что останавливает - дизайн или цена?"
        assert len(questions_in(text)) == 2

    def test_link_tail_is_not_a_question(self):
        """«…jpg?quality=95» — не вопрос: внутри ссылки нет буквенного вопроса."""
        assert questions_in("[photo-https://sun9.vkuserphoto.ru/a/RoMf.jpg?as=32x24]") == []

    def test_single_question(self):
        assert len(questions_in("В какой город доставка?")) == 1

    def test_no_questions(self):
        assert questions_in("Заказ передан в работу.") == []


class TestKeepOneQuestion:
    def test_second_question_is_dropped(self):
        """Боевой пинг 08.09, шаг 3 воронки knows_price."""
        text = (
            "Чтобы понять, как лучше оформить заказ: Вы выбираете свитшот для себя "
            "или в подарок? И подскажите, пожалуйста, что сейчас больше "
            "останавливает - дизайн или стоимость?"
        )

        trimmed, dropped = keep_one_question(text)

        assert len(questions_in(trimmed)) == 1
        assert "для себя или в подарок?" in trimmed
        assert len(dropped) == 1
        assert "останавливает" in dropped[0]

    def test_single_question_untouched(self):
        text = "Сергей, подскажите, пожалуйста, в какой город планируете получать?"

        trimmed, dropped = keep_one_question(text)

        assert trimmed == text
        assert dropped == []

    def test_text_without_questions_untouched(self):
        text = "Возвращаюсь к Вашему заказу - придержала для Вас цену со скидкой."

        assert keep_one_question(text) == (text, [])

    def test_three_questions_leave_the_first(self):
        text = "Всё подходит? А цвет выбрали? И город какой?"

        trimmed, dropped = keep_one_question(text)

        assert questions_in(trimmed) == ["Всё подходит?"]
        assert len(dropped) == 2

    def test_photo_token_survives_the_trim(self):
        """Вырезание вопроса не должно рвать ссылку на картинку пополам."""
        token = "[photo-https://sun9.vkuserphoto.ru/a/RoMf.jpg?quality=95]"
        text = f"Какой цвет выберем? А размер подскажете?\n\n{token}"

        trimmed, dropped = keep_one_question(text)

        assert token in trimmed
        assert len(dropped) == 1

    def test_blank_input(self):
        assert keep_one_question("") == ("", [])
