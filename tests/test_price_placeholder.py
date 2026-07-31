"""Плейсхолдер цены в скриптах связок.

Восемь ценовых скриптов из выгрузки ОП обещают 5 990 ₽ и 6 680 ₽ — цифры вписаны
в текст руками и давно разошлись с матрицей, где свитшот стоит 4 990 ₽ по акции.
Скрипты связок уходят клиенту дословно, поэтому цену в них подставляем из матрицы.
"""
import pytest

from app.db.models import DialogType, Product
from app.sales.price_placeholder import format_price, render_price_placeholders


@pytest.fixture
async def products(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add(Product(name="Свитшот Черный", price=5990, min_price=4990, type_id=1))
    db.add(Product(name="Черная футболка", price=2990, min_price=None, type_id=1))
    await db.commit()


class TestFormat:
    @pytest.mark.parametrize(
        "value,expected",
        [(4990, "4\u00a0990\u00a0₽"), (990, "990\u00a0₽"), (10980, "10\u00a0980\u00a0₽")],
    )
    def test_thousands_separated(self, value, expected):
        """Пробелы неразрывные — сумма не должна разъезжаться переносом строки."""
        assert format_price(value) == expected


class TestRender:
    async def test_promo_price_used(self, db, products):
        got = await render_price_placeholders(db, "Стоимость — [цена:свитшот].", type_id=1)
        assert got == "Стоимость — 4\u00a0990\u00a0₽."

    async def test_falls_back_to_base_price(self, db, products):
        """Акционной нет — берём обычную, а не молчим."""
        got = await render_price_placeholders(db, "[цена:футболка] за штуку", type_id=1)
        assert got == "2\u00a0990\u00a0₽ за штуку"

    async def test_unknown_product_leaves_readable_text(self, db, products):
        """Плейсхолдер в глазах клиента недопустим — вырезаем скобки."""
        got = await render_price_placeholders(db, "Цена [цена:вертолёт] сегодня", type_id=1)
        assert got == "Цена вертолёт сегодня"

    async def test_text_without_placeholder_untouched(self, db, products):
        assert await render_price_placeholders(db, "Супер, зафиксировала", type_id=1) == "Супер, зафиксировала"

    async def test_several_placeholders(self, db, products):
        got = await render_price_placeholders(db, "[цена:свитшот] и [цена:футболка]", type_id=1)
        assert got == "4\u00a0990\u00a0₽ и 2\u00a0990\u00a0₽"

    async def test_price_before_discount(self, db, products):
        """«вместо N рублей» — обычная цена из матрицы, не акционная."""
        got = await render_price_placeholders(
            db, "[цена:свитшот] вместо [цена-до-скидки:свитшот]", type_id=1)
        assert got == "4 990 ₽ вместо 5 990 ₽"
