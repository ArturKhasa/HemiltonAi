"""Цена, названная клиенту, закрепляется за диалогом.

10 августа в 12:25 поправили товарную матрицу — и диалоги, которые шли в этот
момент, начали называть новое число. Клиент, с которым в 09:56 согласовали
4 990 ₽, в 13:15 получил счёт на 5 990 ₽ (диалог 142). Замечание ОП от 10
августа, 13:49: «И опять отправила способы оплаты, НО уже со стоимостью 5990
(ранее было 4990), чего уже не нужно было делать».
"""
import pytest

from app.db.models import Client, Dialog, DialogType, Product
from app.sales.price_placeholder import render_price_placeholders


@pytest.fixture
async def dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add(Product(name="Свитшот Черный", price=5990, min_price=4990, type_id=1))
    db.add(Product(name="Черная футболка", price=2990, min_price=2290, type_id=1))
    client = Client(vk_user_id=1, name="Клиент")
    db.add(client)
    await db.flush()
    d = Dialog(client_id=client.id, type_id=1)
    db.add(d)
    await db.commit()
    return d


class TestPin:
    async def test_first_quote_is_remembered(self, db, dialog):
        out = await render_price_placeholders(
            db, "Стоимость - [цена:свитшот]", type_id=1, dialog=dialog,
        )
        assert "5 990" in out
        assert dialog.quoted_prices == {"Свитшот Черный": 5990}

    async def test_matrix_raise_does_not_reach_a_running_dialog(self, db, dialog):
        """Ровно случай диалога 142: цену согласовали, потом подняли прайс."""
        dialog.quoted_prices = {"Свитшот Черный": 4990}

        out = await render_price_placeholders(
            db, "Получается сумма заказа - [цена:свитшот]", type_id=1, dialog=dialog,
        )

        assert "4 990" in out
        assert "5 990" not in out

    async def test_concession_lowers_the_pin(self, db, dialog):
        """Уступка при возражении — единственный разрешённый способ сдвинуть цену."""
        await render_price_placeholders(db, "[цена:свитшот]", type_id=1, dialog=dialog)
        assert dialog.quoted_prices["Свитшот Черный"] == 5990

        out = await render_price_placeholders(
            db, "Сделаю за [минимальная-цена:свитшот]", type_id=1, dialog=dialog,
        )

        assert "4 990" in out
        assert dialog.quoted_prices["Свитшот Черный"] == 4990

    async def test_pin_after_concession_holds_the_lower_price(self, db, dialog):
        """После уступки обычный «[цена:]» не должен возвращать клиента к 5 990 ₽."""
        dialog.quoted_prices = {"Свитшот Черный": 4990}

        out = await render_price_placeholders(
            db, "Итого [цена:свитшот]", type_id=1, dialog=dialog,
        )

        assert "4 990" in out

    async def test_pin_is_per_product(self, db, dialog):
        """Допродажа футболки не должна подхватывать цену свитшота."""
        dialog.quoted_prices = {"Свитшот Черный": 4990}

        out = await render_price_placeholders(
            db, "Футболка - [цена:футболка]", type_id=1, dialog=dialog,
        )

        assert "2 990" in out
        assert dialog.quoted_prices["Черная футболка"] == 2990

    async def test_without_dialog_the_matrix_wins(self, db, dialog):
        """Предпросмотр скрипта в админке показывает актуальный прайс, а не чужой."""
        out = await render_price_placeholders(db, "[цена:свитшот]", type_id=1)
        assert "5 990" in out
