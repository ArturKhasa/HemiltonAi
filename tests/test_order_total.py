"""Сумма заказа — то, что клиенту назвали, а не цена одного товара из матрицы.

РОП, 03.09: «клиент пришёл за комплектом, ИИ отправляет ему цену на один
свитшот. Нужно прям срочно исправить».

Расчёт под метку уходил правильный — у рекламной метки свой ценовой скрипт
(комплект: толстовка 5 490 ₽ + жилетка 3 490 ₽ = 8 980 ₽). А шаг оформления
называл сумму через «[цена:свитшот]»: цену ОДНОГО изделия из матрицы, одинаковую
для всех. Комплекта в матрице нет, варианта скрипта под метку у оформления тоже —
и клиент видел «сумма заказа 5 990 ₽». За две недели 133 таких сообщения.
"""
import pytest

from app.db.models import Client, Dialog, DialogType, Message, MessageRole, Product, Script
from app.sales.price_placeholder import format_price, render_price_placeholders
from app.sales.prices import order_total
from app.vk.outgoing import mark_failed

KIT = (
    "Расскажу по цене:\n"
    "- Толстовка (хлопок 85%) - 5490р\n"
    "- Демисезонная жилетка непромокаемая - 3490р\n\n"
    "Комплект из двух изделий со скидкой - 8.980р (вместо 12 480р)"
)
ONE = "Стоимость толстовки с термо-принтами со скидкой СЕГОДНЯ - 5 990 ₽ (вместо 7 990 ₽)"
CHECKOUT = "Получается сумма заказа - [сумма-заказа:свитшот]"


class TestOrderTotal:
    def test_kit_takes_the_total_not_the_parts(self):
        """Итог комплекта — 8 980, а не 5 490 и не 3 490."""
        assert order_total([KIT]) == 8980

    def test_struck_through_price_is_not_the_total(self):
        """«(вместо 12 480р)» — зачёркнутая цена, она всегда больше настоящей."""
        assert order_total([ONE]) == 5990
        assert order_total(["Специально для Вас - 4 990 ₽ вместо 5 990 ₽"]) == 4990

    @pytest.mark.parametrize("text", [
        "Доставка СДЭК от 890₽, оплата при получении",
        "Первая оплата всего 500 рублей, далее 50% от стоимости",
        "Зафиксировала размер! Теперь давайте согласуем дизайн",
    ])
    def test_small_change_and_plain_text_are_not_a_total(self, text):
        assert order_total([text]) is None

    def test_latest_price_message_wins(self):
        """После возражения «дорого» цена идёт вниз — заказ стоит столько,
        сколько названо последним, а не сколько было в начале."""
        newest_first = ["Дизайн согласован", "Скидка для Вас - 4 990 ₽", KIT]
        assert order_total(newest_first) == 4990


PRICE_SCRIPT_ID = 367
KIT_SCRIPT_ID = 519
CHECKOUT_SCRIPT_ID = 380


@pytest.fixture
async def dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add(Product(name="Свитшот Черный", price=5990, discount_price=5490,
                   min_price=4990, type_id=1, is_active=True))
    # Ценовой скрипт узнаётся по плейсхолдеру в тексте, его вариант под метку —
    # по ссылке variant_of_script_id: у комплекта цены выписаны числами.
    db.add(Script(id=PRICE_SCRIPT_ID, condition="2.2 Стоимость", type_id=1,
                  phrase_text=ONE.replace("5 990 ₽", "[цена:свитшот]")))
    db.add(Script(id=KIT_SCRIPT_ID, condition="Комплект", type_id=1,
                  marketing_tag="hood141", variant_of_script_id=PRICE_SCRIPT_ID,
                  phrase_text=KIT))
    db.add(Script(id=CHECKOUT_SCRIPT_ID, condition="Оформление", type_id=1,
                  phrase_text=CHECKOUT))
    client = Client(vk_user_id=764732525, name="Никита")
    db.add(client)
    await db.flush()
    d = Dialog(client_id=client.id, type_id=1)
    db.add(d)
    await db.commit()
    return d


async def _sent(db, dialog, text, role=MessageRole.ai, script_id=None):
    db.add(Message(
        dialog_id=dialog.id, role=role, text=text,
        external_message_id=f"vk{dialog.id}{len(text)}{script_id or 0}",
        msg_metadata={"source_script_id": script_id} if script_id else None,
    ))
    await db.commit()


class TestCheckoutScript:
    async def test_kit_client_sees_the_kit_price(self, db, dialog):
        """Диалог 82977: метка на комплект, а в сумме заказа было 5 990 ₽."""
        await _sent(db, dialog, KIT, script_id=KIT_SCRIPT_ID)

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(8980)}"

    async def test_ordinary_client_still_sees_the_single_item_price(self, db, dialog):
        await _sent(db, dialog, ONE, script_id=PRICE_SCRIPT_ID)

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(5990)}"

    async def test_discount_carries_into_the_total(self, db, dialog):
        """Уступили 4 990 — в оформлении обязана стоять уступленная цена."""
        await _sent(db, dialog, ONE, script_id=PRICE_SCRIPT_ID)
        await _sent(db, dialog, "Хорошо, специально для Вас - 4 990 ₽ вместо 5 990 ₽",
                    script_id=PRICE_SCRIPT_ID)

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(4990)}"

    async def test_falls_back_to_the_matrix_when_no_price_was_quoted(self, db, dialog):
        """Цену ещё не называли — берём товар из скобок, как было раньше."""
        await _sent(db, dialog, "Никита, какое имя или фамилию напишем на Вашей кофте?")

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(5990)}"

    async def test_broadcast_price_is_ignored(self, db, dialog):
        """«ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА» ушла в 58 тысяч диалогов — к заказу
        эта цена отношения не имеет."""
        await _sent(db, dialog, KIT, script_id=KIT_SCRIPT_ID)
        db.add(Message(
            dialog_id=dialog.id, role=MessageRole.curator, external_message_id="vk999",
            text="🔥 ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА", msg_metadata={"broadcast": True},
        ))
        await db.commit()

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(8980)}"

    async def test_undelivered_price_is_ignored(self, db, dialog):
        """Упавшая отправка осталась строкой в базе, но клиент её не видел."""
        await _sent(db, dialog, KIT, script_id=KIT_SCRIPT_ID)
        failed = Message(dialog_id=dialog.id, role=MessageRole.ai, text="Скидка - 4 990 ₽")
        mark_failed(failed)
        db.add(failed)
        await db.commit()

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(8980)}"

    async def test_clients_own_numbers_do_not_count(self, db, dialog):
        """«у конкурентов 3 500 руб» — это слова клиента, а не наш расчёт."""
        await _sent(db, dialog, KIT, script_id=KIT_SCRIPT_ID)
        await _sent(db, dialog, "А в другом магазине такой же за 3 500 руб", MessageRole.client)

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(8980)}"

    async def test_preview_without_a_dialog_uses_the_matrix(self, db, dialog):
        """Предпросмотр скрипта в админке: диалога нет, показываем цену матрицы."""
        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=None)

        assert text == f"Получается сумма заказа - {format_price(5990)}"


class TestAnchoredOnTheQuoteScript:
    """Итог берётся из РАСЧЁТА, а не из любой последней цифры в переписке."""

    async def test_price_asked_about_a_single_item_does_not_become_the_total(
        self, db, dialog,
    ):
        """Диалог 83014: расчёт на комплект, следом вопрос про жилетку — и
        «последняя названная цена» превратила заказ в безрукавку за 4 090 ₽."""
        await _sent(db, dialog, KIT, script_id=KIT_SCRIPT_ID)
        await _sent(db, dialog, "Безрукавка - это демисезонная жилетка, её стоимость 4 090 ₽")

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(8980)}"

    async def test_own_wrong_total_is_not_a_source(self, db, dialog):
        """Диалог 82977: сумма уже ушла неверной. Считать по собственному выводу
        значит закрепить ошибку навсегда."""
        await _sent(db, dialog, KIT, script_id=KIT_SCRIPT_ID)
        await _sent(db, dialog, "Получается сумма заказа - 5 990 ₽",
                    script_id=CHECKOUT_SCRIPT_ID)

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(8980)}"

    async def test_manual_arithmetic_is_not_guessed_from_the_text(self, db, dialog):
        """Диалог 82426: менеджер вёл заказ руками и написал «Остаток составляет
        8080 руб» — это остаток после предоплаты, а не сумма заказа. Угадывать
        сумму по свободному тексту не беремся: возвращаемся к цене матрицы."""
        await _sent(db, dialog, "Ранее Вы оплатили 500 руб. Остаток составляет 8080 руб.",
                    role=MessageRole.curator)

        text = await render_price_placeholders(db, CHECKOUT, type_id=1, dialog=dialog)

        assert text == f"Получается сумма заказа - {format_price(5990)}"
