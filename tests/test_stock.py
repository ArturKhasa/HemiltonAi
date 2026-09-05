"""Стоп на цвет: галочка «Активен» в товарной матрице.

Лена, 04.09: «вчера распродали один из цветов для свитшотов. Я в скриптах
заменила картинку, но ИИ до сих пор знает, что этот цвет у нас в наличии».
Фото в скрипте — не рычаг: палитра лежит одной картинкой на все цвета сразу.
Рычаг — `Product.is_active`, и с 05.09 он доезжает до модели (блок контекста)
и до клиента (оговорка рядом с палитрой).

Гранулярность — цвет целиком: ответ заказчика 05.09, «пока достаточно только
цвета».
"""
import pytest

from app.db.models import DialogType, Product
from app.sales.stock import (
    color_of,
    format_sold_out_block,
    sold_out_colors,
    sold_out_names,
)


@pytest.fixture
async def matrix(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add_all([
        Product(id=1, type_id=1, name="Свитшот Черный", is_active=False),
        Product(id=2, type_id=1, name="Свитшот Бежевый", is_active=True),
        Product(id=3, type_id=1, name="Свитшот Темно-Серый (Графит)", is_active=False),
        Product(id=4, type_id=1, name="Черный худи", is_active=False),
        Product(id=5, type_id=1, name="Белый худи", is_active=True),
        Product(id=6, type_id=1, name="Подарочная коробка (упаковка)", is_active=False),
    ])
    await db.flush()
    return db


class TestSoldOutNames:
    async def test_only_deactivated_rows(self, matrix):
        names = await sold_out_names(matrix, type_id=1)
        assert names == [
            "Свитшот Черный",
            "Свитшот Темно-Серый (Графит)",
            "Черный худи",
            "Подарочная коробка (упаковка)",
        ]

    async def test_everything_in_stock_gives_nothing(self, db):
        db.add(DialogType(id=1, name="default", display_name="Основное"))
        db.add(Product(id=1, type_id=1, name="Свитшот Черный", is_active=True))
        await db.flush()
        assert await sold_out_names(db, type_id=1) == []


class TestSoldOutBlock:
    def test_empty_when_everything_is_in_stock(self):
        """Пока в матрице всё активно, в контекст хода не уходит ничего."""
        assert format_sold_out_block([]) == ""

    def test_lists_what_is_gone_and_forbids_offering_it(self):
        block = format_sold_out_block(["Свитшот Черный", "Черный худи"])
        assert block.startswith("[Нет в наличии]")
        assert "- Свитшот Черный" in block
        assert "- Черный худи" in block
        assert "Не предлагай их" in block


class TestColorOf:
    @pytest.mark.parametrize("name,expected", [
        ("Свитшот Черный", "черный"),
        ("Черный худи", "черный"),
        ("Свитшот Темно-Серый (Графит)", "темно-серый (графит)"),
        ("Бежевое худи", "бежевое"),
        ("Черная жилетка", "черная"),
    ])
    def test_product_word_is_stripped(self, name, expected):
        assert color_of(name) == expected

    def test_single_word_name_survives(self):
        """«Рюкзак» — цвета в названии нет вовсе, лучше сказать длинно, чем пусто."""
        assert color_of("Рюкзак") == "рюкзак"


class TestSoldOutColors:
    NAMES = [
        "Свитшот Черный",
        "Свитшот Темно-Серый (Графит)",
        "Черный худи",
        "Подарочная коробка (упаковка)",
    ]

    def test_sweatshirt_palette_lists_only_sweatshirt_colors(self):
        assert sold_out_colors(self.NAMES, wants_hoodie=False) == [
            "черный", "темно-серый (графит)",
        ]

    def test_hoodie_palette_lists_only_hoodie_colors(self):
        assert sold_out_colors(self.NAMES, wants_hoodie=True) == ["черный"]

    def test_non_palette_items_never_leak(self):
        """Подарки, вышивка, кепки к картинке с цветами свитшота отношения не
        имеют — в оговорку они попасть не должны."""
        for wants_hoodie in (True, False):
            assert "подарочная коробка (упаковка)" not in sold_out_colors(
                self.NAMES, wants_hoodie=wants_hoodie,
            )

    def test_zip_hoodie_is_not_a_sweatshirt_color(self):
        assert sold_out_colors(["Черный зип-худи"], wants_hoodie=False) == []

    def test_duplicates_collapse(self):
        """Один цвет в двух позициях — в оговорке он один раз."""
        assert sold_out_colors(
            ["Свитшот Черный", "Свитшот черный"], wants_hoodie=False,
        ) == ["черный"]
