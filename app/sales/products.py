"""Поиск по товарной матрице.

Матрицу заполняют вручную, и названия в ней непоследовательны: свитшоты идут
существительным вперёд («Свитшот Черный»), худи — прилагательным («Черный худи»),
а род прилагательного скачет между позициями («Бежевое худи» против «Свитшот
Бежевый»). Поэтому поиск не может опираться ни на порядок слов, ни на точную
словоформу: раньше он сравнивал запрос целиком как подстроку и на «худи черный»
отвечал «не найдено» (диалог 9 на проде — агент сообщил клиенту, что чёрные худи
закончились, хотя они есть), а на «бежевый худи» отвечал так же из-за окончания
и агент выдумал цену.

Поэтому: запрос режется на слова, у каждого отсекается изменяемое окончание, и
товар обязан содержать ВСЕ полученные основы — в любом порядке и любом роде.
"""
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product

# Отсекаем от длинных к коротким, иначе «бежевого» обрежется до «бежевог».
_ENDINGS = (
    "ого", "его", "ому", "ему", "ыми", "ими",
    "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ом", "ем",
    "ах", "ях", "ам", "ям", "ов", "ев", "ью", "ья", "ье",
    "а", "я", "о", "е", "ы", "и", "у", "ю", "й",
)
# Ниже трёх букв основа перестаёт различать товары («бежевый» → «беж» ещё
# осмысленно, а двухбуквенный огрызок совпадёт с чем угодно).
_MIN_STEM_LEN = 3

# Дефис держим внутри слова: «темно-серый» — одна основа, иначе «темно» соберёт
# и синий, и зелёный. Всё прочее (в т.ч. % и _ из LIKE) отбрасываем.
_WORD_RE = re.compile(r"[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*")


def _stem(word: str) -> str:
    for ending in _ENDINGS:
        if len(word) - len(ending) >= _MIN_STEM_LEN and word.endswith(ending):
            return word[: -len(ending)]
    return word


def build_search_terms(query: str) -> list[str]:
    """Запрос → список основ для сопоставления. Пустой список = искать нечего."""
    normalized = (query or "").lower().replace("ё", "е")
    return [_stem(w) for w in _WORD_RE.findall(normalized)]


def _normalized_name():
    """ё/Ё и е/Е — разные кодпоинты, но в обычном письме взаимозаменяемы (многие
    просто не печатают «ё»). Приводим колонку к нижнему регистру и к «е», запрос
    нормализуется так же в build_search_terms — сравнение идёт LIKE, не ILIKE."""
    return func.replace(func.lower(Product.name), "ё", "е")


class ProductService(object):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_active(self, type_id: int | None = None) -> list[Product]:
        q = select(Product).where(Product.is_active == True)
        if type_id is not None:
            q = q.where(Product.type_id == type_id)
        result = await self.db.execute(q.order_by(Product.id))
        return list(result.scalars().all())

    async def _by_terms(
        self, terms: list[str], type_id: int | None, limit: int
    ) -> list[Product]:
        q = select(Product).where(Product.is_active == True)
        for term in terms:
            q = q.where(_normalized_name().like(f"%{term}%"))
        if type_id is not None:
            q = q.where(Product.type_id == type_id)
        result = await self.db.execute(q.order_by(Product.id).limit(limit))
        return list(result.scalars().all())

    async def search(
        self, query: str, type_id: int | None = None, limit: int = 10
    ) -> list[Product]:
        """Товары, чьё название содержит основы ВСЕХ слов запроса (в любом порядке).

        Точное совпадение названия идёт первым: «Доп. принт» содержится и в «Доп.
        принт - градиент», а тот стоит в матрице раньше — и плейсхолдер
        «[цена:Доп. принт]» подставлял бы 1 990 ₽ вместо 890 ₽.
        """
        terms = build_search_terms(query)
        if not terms:
            return []
        rows = await self._by_terms(terms, type_id, limit)
        wanted = (query or "").strip().lower().replace("ё", "е")
        exact = [p for p in rows if (p.name or "").strip().lower().replace("ё", "е") == wanted]
        if not exact:
            return rows
        return exact + [p for p in rows if p not in exact]

    async def search_loose(
        self, query: str, type_id: int | None = None, limit: int = 10
    ) -> tuple[str | None, list[Product]]:
        """Запасной проход по одному слову запроса, когда точного совпадения нет:
        «беж свитшот» ничего не даёт, «свитшот» — даёт.

        Слова пробуем от длинного к короткому и берём ПЕРВОЕ, по которому что-то
        нашлось. Раньше брали только самое длинное, и «фиолетовый свитшот» уходил
        в пустоту: «фиолетовый» длиннее «свитшота», такого цвета в матрице нет, и
        агент не видел ни одного свитшота — а значит и не мог сказать клиенту,
        какие цвета есть (замечание ОП от 6 августа).

        Возвращает (слово, товары); вызывающий обязан сказать агенту, что это
        расширенный поиск, — иначе тот примет находку за точный ответ.
        """
        terms = build_search_terms(query)
        if len(terms) < 2:
            return None, []
        for term in sorted(terms, key=len, reverse=True):
            found = await self._by_terms([term], type_id, limit)
            if found:
                return term, found
        return None, []

    async def create(
        self, name: str, price=None, min_price=None, size_chart: str | None = None,
        photo_url: str | None = None, type_id: int | None = None,
    ) -> Product:
        product = Product(
            name=name, price=price, min_price=min_price, size_chart=size_chart,
            photo_url=photo_url, type_id=type_id,
        )
        self.db.add(product)
        await self.db.flush()
        return product

    async def update(self, product_id: int, **fields) -> Product | None:
        product = await self.db.get(Product, product_id)
        if not product:
            return None
        for k, v in fields.items():
            setattr(product, k, v)
        await self.db.flush()
        return product

    async def delete(self, product_id: int) -> bool:
        product = await self.db.get(Product, product_id)
        if not product:
            return False
        await self.db.delete(product)
        return True
