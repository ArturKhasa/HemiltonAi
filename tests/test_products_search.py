"""Поиск по товарной матрице.

Все запросы ниже — реальные, из ai_runs на проде. Четыре из них возвращали
«Товары не найдены», после чего агент сообщал клиенту, что позиция закончилась,
а в одном случае ещё и выдумал цену (диалоги 9 и 10, 30.07.2026).
"""
import pytest

from app.db.models import DialogType, Product
from app.sales.products import ProductService, build_search_terms


# Названия из product_matrix.csv как есть — с разнобоем в порядке слов и роде.
MATRIX = [
    "Свитшот Черный",
    "Свитшот Бежевый",
    "Свитшот Белый",
    "Свитшот Темно-Серый (Графит)",
    "Свитшот Темно-Синий",
    "Черный худи",
    "Белый худи",
    "Бежевое худи",
    "Черный зип-худи",
    "Черная жилетка",
    "Белая футболка",
    "Лонгслив черный",
    "Черный костюм с худи и штанами",
]


@pytest.fixture
async def products(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    for name in MATRIX:
        db.add(Product(name=name, price=5990, min_price=4990, size_chart="50-130кг", type_id=1))
    await db.commit()
    return ProductService(db)


async def _names(svc, query):
    return [p.name for p in await svc.search(query)]


class TestStemming:
    """build_search_terms — чистая функция, без БД."""

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("худи черный", ["худ", "черн"]),
            ("бежевый худи", ["бежев", "худ"]),
            ("беж свитшот", ["беж", "свитшот"]),
            ("белое худи", ["бел", "худ"]),
            ("чёрные худи", ["черн", "худ"]),          # ё нормализуется в е
            ("темно-серый свитшот", ["темно-сер", "свитшот"]),  # дефис не рвём
            ("свитшот", ["свитшот"]),
            ("", []),
        ],
    )
    def test_terms(self, query, expected):
        assert build_search_terms(query) == expected

    def test_like_wildcards_stripped(self):
        """Запрос приходит от модели — % и _ не должны становиться шаблоном LIKE."""
        assert build_search_terms("%худи%") == ["худ"]
        assert build_search_terms("_") == []


class TestWordOrder:
    """Свитшоты названы «Свитшот Черный», худи — «Черный худи». Модель применяет
    один порядок слов к обоим и раньше промахивалась ровно на одном из них."""

    async def test_noun_first(self, products):
        assert await _names(products, "свитшот черный") == ["Свитшот Черный"]

    async def test_adjective_first(self, products):
        assert await _names(products, "черный свитшот") == ["Свитшот Черный"]

    async def test_prod_regression_hoodie_black(self, products):
        """Диалог 9: «худи черный» → «не найдено» → «чёрные худи закончились»."""
        assert "Черный худи" in await _names(products, "худи черный")


class TestAdjectiveGender:
    """«Бежевое худи», но «Свитшот Бежевый» — точная словоформа не совпадает."""

    async def test_prod_regression_beige_hoodie(self, products):
        """Диалог 10: «бежевый худи» → «не найдено» → бот выдумал цену 4290₽."""
        assert await _names(products, "бежевый худи") == ["Бежевое худи"]

    async def test_neuter_query_matches_masculine_name(self, products):
        assert await _names(products, "белое худи") == ["Белый худи"]

    async def test_feminine_query_matches_feminine_name(self, products):
        assert await _names(products, "футболка белая") == ["Белая футболка"]


class TestLooseFallback:
    async def test_prod_regression_abbreviation(self, products):
        """Диалог 10: «беж свитшот» — сокращение, точного совпадения нет."""
        assert await _names(products, "беж свитшот") == ["Свитшот Бежевый"]

    async def test_falls_back_to_widest_word(self, products):
        """Слова по отдельности осмысленны, вместе — нет. Отдаём по «свитшот»."""
        term, found = await products.search_loose("свитшот с капюшоном")
        assert term == "свитшот"
        assert "Свитшот Черный" in [p.name for p in found]

    async def test_single_word_query_has_no_fallback(self, products):
        """Одно слово уже искали в search() — расширять нечего."""
        assert await products.search_loose("цвет") == (None, [])


class TestNoFalsePositives:
    async def test_unrelated_query_finds_nothing(self, products):
        assert await _names(products, "цвет") == []

    async def test_hyphen_kept_together(self, products):
        """«темно» в одиночку собрало бы и Темно-Синий тоже."""
        assert await _names(products, "темно-серый свитшот") == ["Свитшот Темно-Серый (Графит)"]

    async def test_all_terms_required(self, products):
        """AND, не OR: «зип» отсеивает обычные худи."""
        assert await _names(products, "зип худи") == ["Черный зип-худи"]

    async def test_inactive_product_hidden(self, db, products):
        db.add(Product(name="Свитшот Фиолетовый", price=5990, is_active=False, type_id=1))
        await db.commit()
        assert await _names(products, "фиолетовый свитшот") == []


class TestLooseSearchFallsThrough:
    """«фиолетовый свитшот»: такого цвета в матрице нет, а «фиолетовый» длиннее
    «свитшота» — расширенный поиск шёл только по нему и не находил ничего.
    Агент не видел ни одного свитшота и не мог сказать, какие цвета есть."""

    async def test_unknown_colour_still_lists_the_item(self, db):
        from app.db.models import Product
        from app.sales.products import ProductService

        for name in ("Свитшот Черный", "Свитшот Бежевый", "Худи Черное"):
            db.add(Product(name=name, price=5990, is_active=True, type_id=1))
        await db.commit()

        term, found = await ProductService(db).search_loose("фиолетовый свитшот", type_id=1)
        assert term == "свитшот"
        assert {p.name for p in found} == {"Свитшот Черный", "Свитшот Бежевый"}

    async def test_nothing_matches_at_all(self, db):
        from app.db.models import Product
        from app.sales.products import ProductService

        db.add(Product(name="Свитшот Черный", price=5990, is_active=True, type_id=1))
        await db.commit()

        term, found = await ProductService(db).search_loose("фиолетовая шапка", type_id=1)
        assert term is None and found == []
