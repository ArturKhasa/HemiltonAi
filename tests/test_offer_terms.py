"""Условия акции, которые модель достраивала за нас.

Все «плохие» примеры — дословные реплики из диалога 343 от 17.08, все три
обещания потом отыгрывал назад живой менеджер.
"""
import pytest

from app.sales.offer_terms import (
    data_requested_after_payment,
    hedges_delivery_price,
    promises_both_gifts,
    promises_offer_another_day,
    promises_to_return,
)


class TestDataAfterPayment:
    @pytest.mark.parametrize("reply", [
        "Да, завтра можно внести всю сумму сразу. После оплаты пришлите, пожалуйста, "
        "ФИО и телефон получателя - оформлю заказ.",
        "Как оплатите, напишите ФИО и номер телефона получателя?",
        "После внесения предоплаты пришлите ФИО и телефон получателя.",
    ])
    def test_reversed_order_caught(self, reply):
        assert data_requested_after_payment(reply) is True

    @pytest.mark.parametrize("reply", [
        "Отлично, тогда подскажите, пожалуйста, ФИО и номер телефона получателя "
        "посылки, выставлю счет на предоплату ❤",
        "Напишете ФИО и телефон получателя? Счёт придёт следующим сообщением.",
        # Просьба про чек после оплаты — законна, данных получателя тут нет.
        "После оплаты пришлите, пожалуйста, чек.",
        # Оба смысла есть, но в разных предложениях — порядок не нарушен.
        "Пришлите ФИО и телефон получателя. После оплаты отправлю чек.",
    ])
    def test_correct_order_allowed(self, reply):
        assert data_requested_after_payment(reply) is False


class TestBothGifts:
    @pytest.mark.parametrize("reply", [
        "Да, можно выбрать оба подарка - кепку и белую футболку.",
        "При оплате всей суммы завтра зафиксирую оба подарка.",
        "Кепка и белая футболка будут подарками при оплате всей суммы.",
        "Положу и кепку, и майку в подарок.",
    ])
    def test_both_gifts_caught(self, reply):
        assert promises_both_gifts(reply) is True

    @pytest.mark.parametrize("reply", [
        "Подарок кладём один на выбор - кепка или белая футболка. Какой оставим?",
        "Можно внести всю сумму и получить подарок на выбор - кепку с нашивкой "
        "флага РФ или белую футболку ❤️",
        "Выбрали кепку - зафиксировала. Какой цвет свитшота возьмём?",
    ])
    def test_single_gift_allowed(self, reply):
        assert promises_both_gifts(reply) is False


class TestOfferAnotherDay:
    @pytest.mark.parametrize("reply", [
        "Да, завтра можно внести всю сумму сразу и получить подарок на выбор.",
        "При оплате всей суммы завтра зафиксирую подарок.",
        "Кепка будет подарком при оплате всей суммы в понедельник.",
        "Оплатите на следующей неделе - скидка сохранится.",
    ])
    def test_deferred_offer_caught(self, reply):
        assert promises_offer_another_day(reply) is True

    @pytest.mark.parametrize("reply", [
        # Правильная отработка переноса: бронь.
        "Скидочка действует в день обращения. Можем забронировать за Вами цену и "
        "подарок, если внесёте 500 ₽ - оплатить остальное сможете завтра.",
        # Про подарок сегодня — как в скрипте.
        "Сегодня при полной оплате подарок на выбор Ваш. Оформляем?",
        # Завтра, но не про акцию.
        "Макет дизайнер подготовит завтра, покажу Вам на согласование.",
        "Отправим СДЭКом завтра, доставка оплачивается при получении.",
    ])
    def test_legitimate_replies_allowed(self, reply):
        assert promises_offer_another_day(reply) is False


class TestDeliveryPrice:
    """Стоимость доставки известна и одна — уходить от неё нельзя.

    Лена, 21.08: «Можно зафиксировать, что стоимость доставки СДЭКом фикс. по
    всем направлениям - 1000р, она оплачивается при получении после просмотра и
    примерки». До этого суммы не было нигде, и на прямой вопрос клиента модель
    отвечала «её стоимость зависит от города» (диалог 75800, 20.08 23:15).
    """

    @pytest.mark.parametrize("text", [
        "Доставка оплачивается при получении, её стоимость зависит от города.",
        "Стоимость доставки уточню и напишу Вам.",
        "Доставку СДЭКом рассчитаем при оформлении.",
    ])
    def test_hedging_is_caught(self, text):
        assert hedges_delivery_price(text)

    @pytest.mark.parametrize("text", [
        "Доставка СДЭК - 1 000 ₽ по всем направлениям, оплачиваете при получении.",
        "В Белорецк отправляем СДЭКом - быстрее и выгоднее Почты.",
        "Вышивка нитками не входит в стоимость и рассчитывается индивидуально.",
    ])
    def test_a_straight_answer_passes(self, text):
        assert not hedges_delivery_price(text)

    def test_the_rule_is_in_the_prompt(self):
        from app.ai.prompts import _SALES_PROMPT_FALLBACK

        assert "## Доставка" in _SALES_PROMPT_FALLBACK
        assert "1 000 ₽" in _SALES_PROMPT_FALLBACK
        assert "примерит" in _SALES_PROMPT_FALLBACK


class TestPromisesToReturn:
    """Обещание вернуться с ответом ИИ исполнить не может — следующего хода у неё
    нет. Регламент сам предписывает эту фразу на срочных сроках, поэтому её не
    запрещают, а передают человеку. За неделю ушла трижды."""

    @pytest.mark.parametrize("text", [
        "Уточню у руководителя отдела продаж, успеем ли к этой дате, и вернусь с ответом",
        "Уточню у производства и вернусь",
        "Сообщу позже",
        "Напишу вам как только узнаю сроки",
        "Уточню у дизайнера и вернусь с ответом",
    ])
    def test_promise_escalates(self, text):
        assert promises_to_return(text) is True

    @pytest.mark.parametrize("text", [
        "Я уточню, какой цвет вам подойдёт",
        "Уточните, пожалуйста, ваш рост и вес",
        "В какой город нужна доставка?",
        "Сейчас всё зафиксирую и отправлю расчёт",
    ])
    def test_ordinary_replies_pass(self, text):
        assert promises_to_return(text) is False
