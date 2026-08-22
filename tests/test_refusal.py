"""Отказ клиента — не согласие: воронку он останавливает, а не двигает.

Диалог 89, 11:24-11:25: на «Спасибо не надо», «Не надо» и «Не надо мне» модель
трижды прислала ту же сверку дизайна, а на третий раз написала «фиксирую под Вас
этот вариант» — и следом развернулась связка со счётом на 4 990 ₽.
"""
import pytest

from app.sales.funnel_steps import (
    client_refused,
    client_walks_away,
    lets_client_go,
    places_inscription_in_the_center,
    reply_advances_funnel,
)


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
        "Пока ничего не нужно",
        "Пока не надо",
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


class TestLetsClientGo:
    """«Пока ничего не нужно» — и в ответ «Хорошо, поняла. Если решите вернуться
    к заказу, напишите мне» (Сергей Ескин, 10:40). Причину отказа никто не узнал.

    ОП, 22.08: «Если клиент говорит, что ему ничего не нужно, то мы всегда
    обязательно уточняем, что именно ему не подошло. Клиента просто так не
    отпускаем думать/возвращаться к диалогу когда ему будет удобно»."""

    @pytest.mark.parametrize("text", [
        "Хорошо, поняла. Если решите вернуться к заказу, напишите мне.",
        "Договорились, поняла. Если снова понадобится изготовление, вернётесь к этому вопросу позже?",
        "Поняла Вас, буду на связи!",
        "Хорошо, обращайтесь, если что)",
        "Спасибо за обращение, хорошего дня!",
        "Приняла, тогда не буду отвлекать.",
    ])
    def test_farewell_instead_of_a_question(self, text):
        assert lets_client_go(text) is True

    @pytest.mark.parametrize("text", [
        "Поняла Вас. Подскажите, что именно не подошло - цена или сроки?",
        "Жаль это слышать) А что Вас остановило?",
        "Слышу Вас. В чём причина - дизайн или стоимость?",
        "Понимаю. Скажите, пожалуйста, что не устроило в предложении?",
    ])
    def test_asking_the_reason_is_fine(self, text):
        assert lets_client_go(text) is False

    def test_farewell_with_a_question_still_lets_go(self):
        """Вопрос есть, но он про «вернётесь позже», а не про причину отказа."""
        assert lets_client_go(
            "Хорошо! Если станет актуально, напишете мне?"
        ) is True


class TestClientWalksAway:
    """Голое «Нет» чаще отвечает на наш же вопрос, чем закрывает разговор.
    В диалоге 77116 (22.08, 12:09) «Нет» пришло на «Всё верно?» и правило дизайн,
    в 76943 — «Нет нет, два варианта хочу увидеть». Дожимать причину там незачем."""

    @pytest.mark.parametrize("text", [
        "Пока ничего не нужно",
        "Не надо",
        "Спасибо, не нужно.",
        "Спасибо откажусь",
        "Не актуально",
        "Передумал",
        "Нет, спасибо",
    ])
    def test_walk_away(self, text):
        assert client_walks_away(text) is True

    @pytest.mark.parametrize("text", [
        "Нет",
        "Нет)",
        "нет нет",
        "Нет название Димитров",
        "Да",
    ])
    def test_bare_no_is_not_a_walk_away(self, text):
        assert client_walks_away(text) is False


class TestPraiseOnRefusal:
    """Диалог 77117, 22.08 12:10: на «Не надо» ушёл скрипт «2. Похвала», и связка
    развернула следом прайс и доставку. Условие скрипта прямо велит применять его
    «чем бы клиент ни ответил» — держать его должен код."""

    ADVANCING = {363, 379, 380, 381}

    def test_praise_script_advances(self):
        assert reply_advances_funnel(
            "Супер, зафиксировала\nСделаем всё как Вы хотите!", 363, self.ADVANCING,
        ) is True

    def test_praise_text_advances_without_script_id(self):
        assert reply_advances_funnel(
            "Супер, зафиксировала\nСделаем всё как Вы хотите!", None, self.ADVANCING,
        ) is True

    def test_ordinary_confirmation_does_not_advance(self):
        assert reply_advances_funnel(
            "Серый цвет зафиксировала. Какой у Вас рост?", None, self.ADVANCING,
        ) is False


class TestCenterPlacement:
    """Раскладку код рисует сам, но своими словами модель по-прежнему ставит
    надпись по центру (диалоги 76950 и 77116)."""

    @pytest.mark.parametrize("text", [
        "Надпись размещаем на груди по центру. Всё верно?",
        "Супер, зафиксировала: • Надпись «Екатерина Федулова» • Размещаем по центру груди",
        "Имя нанесём спереди посередине, всё верно?",
    ])
    def test_center_is_caught(self, text):
        assert places_inscription_in_the_center(text, []) is True

    def test_client_asked_for_the_center_himself(self):
        assert places_inscription_in_the_center(
            "Хорошо, надпись разместим по центру груди. Всё верно?",
            ["давайте по центру"],
        ) is False

    @pytest.mark.parametrize("text", [
        "На груди справа - надпись «Андрей». Всё верно?",
        "Доставка в центре города, пункт СДЭК рядом. Всё верно?",
    ])
    def test_no_false_positives(self, text):
        assert places_inscription_in_the_center(text, []) is False
