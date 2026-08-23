"""Рассылка не должна глушить ИИ.

20-22 августа из 262 диалогов, где ИИ замолчала, 106 заглушила массовая рассылка
группы, а не менеджер: «Вы помните, что сегодня День Государственного флага?»,
«костюм за 1 руб.» и ещё 70 шаблонов ушли в десятки тысяч диалогов, и каждый
такой диалог код прочитал как «его забрал живой оператор».
"""
import pytest

from app.vk.broadcast import is_broadcast, reset

MAILING = (
    "Вы помните, что сегодня — День Государственного флага?🇷🇺\n\n"
    "В честь праздника создаём ваш личный символ: свитшот с гербом"
)


@pytest.fixture(autouse=True)
def _clean():
    reset()
    yield
    reset()


class TestIsBroadcast:
    def test_single_manager_reply_is_not_a_broadcast(self):
        assert is_broadcast("да, без проблем) на груди сделать ромб?", 501) is False

    def test_same_text_to_many_dialogs_is_a_broadcast(self):
        verdicts = [is_broadcast(MAILING, did) for did in range(1, 31)]
        assert verdicts[0] is False, "первые диалоги ещё не отличить от ответа человека"
        assert verdicts[-1] is True
        assert sum(verdicts) >= 20

    def test_personalised_mailing_counts_as_one(self):
        """«Александр, костюм за 1 руб.» и «Сергей, костюм за 1 руб.» — одна рассылка."""
        names = ["Александр", "Сергей", "Андрей", "Алексей", "Дмитрий", "Иван",
                 "Пётр", "Роман", "Никита", "Олег", "Павел", "Игорь"]
        verdicts = [
            is_broadcast(f"{name}, костюм за 1 руб. — не ошибка.", i)
            for i, name in enumerate(names)
        ]
        assert verdicts[-1] is True

    def test_repeat_to_the_same_dialog_is_not_a_broadcast(self):
        """Менеджер написал десять сообщений в один диалог — это не рассылка."""
        assert not any(is_broadcast(MAILING, 777) for _ in range(20))

    def test_empty_text_is_treated_as_a_person(self):
        """Голое вложение или стикер по тексту не сравнить — безопаснее пауза."""
        assert any(is_broadcast("", did) for did in range(50)) is False

    def test_different_texts_do_not_add_up(self):
        assert not any(
            is_broadcast(f"Здравствуйте, уточните размер {i}", i) for i in range(30)
        )
