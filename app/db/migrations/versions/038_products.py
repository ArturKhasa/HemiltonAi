"""add products table (товарная матрица)

Revision ID: 038
Revises: 037
Create Date: 2026-07-24

Справочник товаров (название, цена, минимальная цена, размерная сетка, фото)
для инструмента search_products — агент подбирает точную цену/сетку по названию
вместо того, чтобы держать весь каталог в промпте.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("dialog_types.id"), nullable=True, server_default="1"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("min_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("size_chart", sa.String(length=255), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("products")
