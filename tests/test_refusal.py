"""Отказ клиента — не согласие: воронку он останавливает, а не двигает.

Диалог 89, 11:24-11:25: на «Спасибо не надо», «Не надо» и «Не надо мне» модель
трижды прислала ту же сверку дизайна, а на третий раз написала «фиксирую под Вас
этот вариант» — и следом развернулась связка со счётом на 4 990 ₽.
"""
import pytest

from app.sales.funnel_steps import client_refused, reply_advances_funnel


class TestClientRefused:
    @pytest.mark.parametrize("text", [
        "Спасибо не надо",
        "Не надо",
        "Не надо мне",
        "не нужно",
        "Не хочу",
        "Нет",
        "нет, не надо",
        "Передумал",
        "Отменяем заказ",
        "Ничего не надо",
        "Не буду оформлять",
    ])
    def test_refusals(self, text):
        assert client_refused(text) is True

    @pytest.mark.parametrize("text", [
        "Да",
        "Да, всё верно",
        "Нет, всё верно",
        "Верно",
        "Давайте оформлять",
        "180 80",
        "Синий",
        "А можно скидку?",
        "",
    ])
    def test_not_refusals(self, text):
        assert client_refused(text) is False

    def test_payment_choice_is_not_a_refusal(self):
        """«Не надо частями» — это выбор способа оплаты, шаг закрыт нормально."""
        assert client_refused("Не надо частями, внесу всю сумму") is False
        assert client_refused("не надо всю сумму, давайте 500") is False

    def test_refusal_must_open_the_message(self):
        """«Не надо переживать» внутри длинной фразы — не отказ клиента."""
        assert client_refused("Хорошо, только не надо мне звонить, пишите сюда") is False


class TestReplyAdvancesFunnel:
    ADVANCING = {379, 380, 381, 382}

    def test_design_fixed_script_advances(self):
        assert reply_advances_funnel("Супер, зафиксировала!", 379, self.ADVANCING) is True

    def test_checkout_text_advances_without_script_id(self):
        text = "Получается сумма заказа - 4 990 ₽\n\nА по оплате у нас есть 2 варианта"
        assert reply_advances_funnel(text, None, self.ADVANCING) is True

    def test_design_fixed_text_advances_without_script_id(self):
        text = "Супер, тогда фиксирую под Вас этот вариант и ставлю его в работу)"
        assert reply_advances_funnel(text, None, self.ADVANCING) is True

    def test_contacts_request_advances(self):
        text = "Отлично, тогда подскажите ФИО и номер телефона получателя"
        assert reply_advances_funnel(text, None, self.ADVANCING) is True

    def test_clarifying_question_does_not_advance(self):
        text = "Поняла Вас. Подскажите, что именно не подошло - цвет или надпись?"
        assert reply_advances_funnel(text, None, self.ADVANCING) is False

    def test_objection_script_does_not_advance(self):
        text = "Понимаю, не буду настаивать. Оставить заказ в силе?"
        assert reply_advances_funnel(text, 412, self.ADVANCING) is False
