"""Плейсхолдер цены в скриптах связок.

Восемь ценовых скриптов из выгрузки ОП обещают 5 990 ₽ и 6 680 ₽ — цифры вписаны
в текст руками и давно разошлись с матрицей, где свитшот стоит 4 990 ₽ по акции.
Скрипты связок уходят клиенту дословно, поэтому цену в них подставляем из матрицы.
"""
import pytest

from app.config import settings
from app.db.models import DialogType, Product
from app.sales.price_placeholder import (
    format_price,
    payment_link_configured,
    render_price_placeholders,
)


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


class TestPaymentLink:
    """Скрипт #382 обещает «вот счёт-ссылка», а ссылки в нём нет — менеджер
    вставляет её руками. Пока платёжной интеграции нет, PAYMENT_LINK_URL пуст:
    до оплаты диалог доводит куратор, а фраза про ссылку клиенту не уходит."""

    async def test_link_substituted_when_configured(self, db, products, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_LINK_URL", "https://pay.example.org/500")
        got = await render_price_placeholders(db, "Вот счёт: [ссылка-оплаты]", type_id=1)
        assert got == "Вот счёт: https://pay.example.org/500"

    async def test_works_together_with_price(self, db, products, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_LINK_URL", "https://pay.example.org/500")
        got = await render_price_placeholders(
            db, "[цена:свитшот] — оплатить: [ссылка-оплаты]", type_id=1)
        assert got.endswith("— оплатить: https://pay.example.org/500")

    async def test_sentence_dropped_when_no_link(self, db, products, monkeypatch):
        """«Вот счёт-ссылка на 500 рублей:» без самой ссылки хуже, чем молчание."""
        monkeypatch.setattr(settings, "PAYMENT_LINK_URL", "")
        got = await render_price_placeholders(
            db, "Спасибо за заказ. Вот счёт: [ссылка-оплаты]", type_id=1)
        assert got == "Спасибо за заказ."

    async def test_price_survives_when_link_is_cut(self, db, products, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_LINK_URL", "")
        got = await render_price_placeholders(
            db, "Сумма — [цена:свитшот].\nОплата: [ссылка-оплаты]", type_id=1)
        assert got.startswith("Сумма —") and "[ссылка-оплаты]" not in got
        assert "Оплата" not in got

    def test_configured_flag(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_LINK_URL", "")
        assert not payment_link_configured()
        monkeypatch.setattr(settings, "PAYMENT_LINK_URL", "https://pay.example.org/500")
        assert payment_link_configured()


class TestExactNameWins:
    """«Доп. принт» содержится и в «Доп. принт - градиент», а тот стоит в матрице
    раньше — плейсхолдер подставлял 1 990 ₽ вместо 890 ₽."""

    async def test_exact_match_is_first(self, db):
        from app.db.models import Product
        from app.sales.products import ProductService

        db.add(Product(name="Доп. принт - градиент", price=2590, min_price=1990, is_active=True, type_id=1))
        db.add(Product(name="Доп. принт", price=1190, min_price=890, is_active=True, type_id=1))
        await db.commit()

        found = await ProductService(db).search("Доп. принт", type_id=1, limit=5)
        assert found[0].name == "Доп. принт"

    async def test_partial_query_keeps_matrix_order(self, db):
        from app.db.models import Product
        from app.sales.products import ProductService

        db.add(Product(name="Свитшот Черный", price=5990, min_price=4990, is_active=True, type_id=1))
        db.add(Product(name="Свитшот Белый", price=5990, min_price=4990, is_active=True, type_id=1))
        await db.commit()

        found = await ProductService(db).search("свитшот", type_id=1, limit=5)
        assert [p.name for p in found] == ["Свитшот Черный", "Свитшот Белый"]


class TestPlaceholderTakesTheExactProduct:
    """LIMIT отсекал строки в SQL до сортировки «точное название вперёд», и
    «[цена:Доп. принт]» подставлял цену градиентного принта."""

    async def test_plain_print_price_not_the_gradient_one(self, db):
        from app.db.models import Product
        from app.sales.price_placeholder import render_price_placeholders

        db.add(Product(name="Доп. принт - градиент", price=2590, min_price=1990, is_active=True, type_id=1))
        db.add(Product(name="Доп. принт", price=1190, min_price=890, is_active=True, type_id=1))
        await db.commit()

        got = await render_price_placeholders(
            db, "скидочка - [цена:Доп. принт] вместо [цена-до-скидки:Доп. принт]", type_id=1,
        )
        # format_price ставит неразрывные пробелы, чтобы сумма не рвалась переносом.
        assert got == "скидочка - 890\u00a0₽ вместо 1\u00a0190\u00a0₽"
