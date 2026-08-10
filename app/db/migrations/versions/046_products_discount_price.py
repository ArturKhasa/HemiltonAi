"""products.discount_price — средняя ступень уступки

ОП (10 августа, 16:28): «Изначально предлагаем за 5990 (вместо 7990). Если есть
возражение дорого: 1. Сначала делаем попытку отработать возражение без скидки,
объяснить клиенту ценность за 5990. 2. Если на отработку по ценности нет реакции
или она негативная, то предлагаем по скидке за 5490. 3. Если реакция снова
негативная, можно предложить за 4990».

В матрице было две колонки — «Цена» и «Минимальная цена», — и скидочный скрипт
прыгал с 5 990 ₽ сразу на 4 990 ₽ через ступень. Колонка необязательная: там, где
её не заполнили, лестница остаётся двухступенчатой, как сейчас, и ни одна
существующая цена не меняется.

Revision ID: 046
Revises: 045
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("discount_price", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "discount_price")
