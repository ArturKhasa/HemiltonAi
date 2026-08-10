"""Лестница скидок: 5990 → отработка ценностью → повторное «дорого» → 5490 → 4990.

Примеры взяты из регламента ОП (10 августа), собранного по разбору живых
диалогов менеджеров. Главное правило: первое «дорого» скидки не открывает, а
«подумаю» и вопросы о товаре — тем более.
"""
import pytest

from app.db.models import Client, Dialog, DialogType, Message, MessageRole, Product
from app.sales.price_objection import (
    concession_allowed,
    is_neutral_reaction,
    is_price_objection,
)
from app.sales.price_placeholder import price_ladder, render_price_placeholders


class TestDetectObjection:
    @pytest.mark.parametrize("text", [
        "Дорого",
        "Что-то дороговато",
        "За такую цену не возьму",
        "У вас дорого",
        "Есть дешевле",
        "Нашел дешевле",
        "На ВБ дешевле",
        "на озоне дешевле",
        "Не готов столько отдавать",
        "Для меня это дорого",
        "Всё равно дорого",
        "Нет, за 5990 не буду брать",
        "Не стоит он этих денег",
        "Мне без разницы, какое там качество, дорого",
        "Нет, я рассчитывал максимум на 5000",
        "Дорого, ищу дешевле",
        "У других дешевле",
        "Спасибо, но слишком дорого",
    ])
    def test_price_resistance_is_recognised(self, text):
        assert is_price_objection(text)

    @pytest.mark.parametrize("text", [
        "Понятно", "Хорошо", "Ясно", "Спасибо", "Подумаю", "Надо подумать",
        "Я ещё посмотрю", "Буду иметь в виду", "Хорошо, понял",
    ])
    def test_neutral_reaction_is_not_an_objection(self, text):
        """«Подумаю» — повод уточнить, что смущает, а не сбросить цену."""
        assert not is_price_objection(text)
        assert is_neutral_reaction(text)

    @pytest.mark.parametrize("text", [
        "А какие размеры есть?", "А цвет какой есть?", "Давайте тогда",
        "Как оформить заказ?", "А доставка сколько?", "Когда сможете отправить?",
        "Есть XL?", "Хорошо, беру",
    ])
    def test_moving_to_the_product_is_not_an_objection(self, text):
        """Клиент ушёл с цены на товар и заказ — это согласие с ценой."""
        assert not is_price_objection(text)


@pytest.fixture
async def dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add(Product(
        name="Свитшот Черный", price=5990, discount_price=5490, min_price=4990, type_id=1,
    ))
    c = Client(vk_user_id=1)
    db.add(c)
    await db.flush()
    d = Dialog(client_id=c.id, type_id=1)
    db.add(d)
    await db.commit()
    return d


async def _say(db, dialog, role, text):
    db.add(Message(dialog_id=dialog.id, role=role, text=text))
    await db.commit()


class TestConcessionGate:
    async def test_first_objection_gives_no_discount(self, db, dialog):
        """«Дорого» в первый раз отрабатывается ценностью, а не ценой."""
        await _say(db, dialog, MessageRole.ai, "Стоимость - 5 990 ₽")
        await _say(db, dialog, MessageRole.client, "Дорого")

        assert await concession_allowed(db, dialog.id, "Дорого") is False

    async def test_repeat_objection_after_value_opens_the_discount(self, db, dialog):
        await _say(db, dialog, MessageRole.ai, "Стоимость - 5 990 ₽")
        await _say(db, dialog, MessageRole.client, "Дорого")
        await _say(db, dialog, MessageRole.ai, "Понимаю. Цена обусловлена качеством ткани")
        await _say(db, dialog, MessageRole.client, "Всё равно дорого, больше 5000 не хочу")

        assert await concession_allowed(
            db, dialog.id, "Всё равно дорого, больше 5000 не хочу",
        ) is True

    async def test_thinking_it_over_does_not_open_the_discount(self, db, dialog):
        """«Подумаю» после отработки — не повторное возражение."""
        await _say(db, dialog, MessageRole.ai, "Стоимость - 5 990 ₽")
        await _say(db, dialog, MessageRole.client, "Дорого")
        await _say(db, dialog, MessageRole.ai, "Понимаю. Ткань плотная, посадка индивидуальная")
        await _say(db, dialog, MessageRole.client, "Подумаю")

        assert await concession_allowed(db, dialog.id, "Подумаю") is False

    async def test_question_about_the_product_does_not_open_the_discount(self, db, dialog):
        await _say(db, dialog, MessageRole.ai, "Стоимость - 5 990 ₽")
        await _say(db, dialog, MessageRole.client, "Дорого")
        await _say(db, dialog, MessageRole.ai, "Понимаю. Шьём сами, ткань плотная")
        await _say(db, dialog, MessageRole.client, "А какие размеры есть?")

        assert await concession_allowed(db, dialog.id, "А какие размеры есть?") is False


class TestLadder:
    def test_three_rungs_in_order(self, db):
        class P:
            price, discount_price, min_price = 5990, 5490, 4990

        assert price_ladder(P()) == [5990, 5490, 4990]

    def test_missing_middle_rung_keeps_two_steps(self):
        class P:
            price, discount_price, min_price = 5990, None, 4990

        assert price_ladder(P()) == [5990, 4990]

    async def test_concession_steps_down_one_rung_at_a_time(self, db, dialog):
        """Скидочный скрипт спускает на ступень от уже названной цены, а не на дно."""
        await render_price_placeholders(db, "[цена:свитшот]", type_id=1, dialog=dialog)
        assert dialog.quoted_prices["Свитшот Черный"] == 5990

        first = await render_price_placeholders(
            db, "[минимальная-цена:свитшот]", type_id=1, dialog=dialog,
        )
        assert "5 490" in first
        assert dialog.quoted_prices["Свитшот Черный"] == 5490

        second = await render_price_placeholders(
            db, "[минимальная-цена:свитшот]", type_id=1, dialog=dialog,
        )
        assert "4 990" in second

    async def test_bottom_rung_is_final(self, db, dialog):
        dialog.quoted_prices = {"Свитшот Черный": 4990}

        out = await render_price_placeholders(
            db, "[минимальная-цена:свитшот]", type_id=1, dialog=dialog,
        )

        assert "4 990" in out
