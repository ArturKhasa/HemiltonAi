"""Товарная матрица — список и стоп на позицию для админки.

Матрица была заведена только через выгрузку (data/onboarding/product_matrix.csv)
и правилась руками в базе: ни эндпоинта, ни экрана у неё не было. Пока по ней
искал только агент, это было терпимо, но 04.09 Лена спросила «как поставить
определённый цвет на стоп?» — и оказалось, что рычаг (`is_active`) в коде есть,
а дотянуться до него из панели нельзя.

Поэтому здесь ровно то, что нужно для этой задачи: показать матрицу и снять или
вернуть галочку «Активен». Заводить и удалять позиции по-прежнему нельзя —
матрицу наполняют выгрузкой, и случайное удаление строки уронило бы цены,
которые подставляются по названию (app.sales.price_placeholder).
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.models import Product, User
from app.db.session import get_db

router = APIRouter(prefix="/products", tags=["products"])


class ProductOut(BaseModel):
    id: int
    type_id: int | None
    name: str
    price: Decimal | None
    discount_price: Decimal | None
    min_price: Decimal | None
    size_chart: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class ProductUpdateRequest(BaseModel):
    is_active: bool


@router.get("/", response_model=list[ProductOut])
async def list_products(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
    type_id: int | None = None,
):
    q = select(Product)
    if type_id is not None:
        q = q.where(Product.type_id == type_id)
    rows = await db.execute(q.order_by(Product.id))
    return list(rows.scalars().all())


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    body: ProductUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """Снять позицию с продажи или вернуть её обратно.

    Снятая позиция пропадает из поиска товара, уходит в блок «Нет в наличии»
    контекста хода и оговаривается рядом с картинкой-палитрой
    (app.sales.stock) — то есть ИИ перестаёт её предлагать сразу же, без
    правки скриптов.
    """
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Позиция не найдена")
    product.is_active = body.is_active
    await db.commit()
    await db.refresh(product)
    return product
