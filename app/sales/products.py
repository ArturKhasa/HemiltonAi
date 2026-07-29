from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product


def _normalize_yo(expr):
    """ё/Ё и е/Е — разные кодпоинты в Unicode, но взаимозаменяемы в обычном русском
    письме (многие вообще не печатают «ё»). Без нормализации ILIKE('чёрный') не
    находит товар «Черный», хотя это один и тот же цвет — см. дефолт наименований
    из товарной матрицы. Приводим обе стороны сравнения к «е»/«е» перед ILIKE."""
    return func.replace(func.replace(expr, "ё", "е"), "Ё", "Е")


class ProductService(object):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_active(self, type_id: int | None = None) -> list[Product]:
        q = select(Product).where(Product.is_active == True)
        if type_id is not None:
            q = q.where(Product.type_id == type_id)
        result = await self.db.execute(q.order_by(Product.id))
        return list(result.scalars().all())

    async def search(self, query: str, type_id: int | None = None, limit: int = 10) -> list[Product]:
        normalized_query = query.replace("ё", "е").replace("Ё", "Е")
        q = select(Product).where(
            Product.is_active == True,
            _normalize_yo(Product.name).ilike(f"%{normalized_query}%"),
        )
        if type_id is not None:
            q = q.where(Product.type_id == type_id)
        result = await self.db.execute(q.order_by(Product.id).limit(limit))
        return list(result.scalars().all())

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
