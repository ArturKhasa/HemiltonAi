"""dialogs.quoted_prices — цена, уже названная клиенту в этом диалоге

Цена бралась из товарной матрицы в момент отправки. 10 августа в 12:25 матрицу
поправили (макрос «[цена:]» переключили с минимальной цены на обычную) — и все
диалоги, которые шли в этот момент, начали называть новое число. Клиент, с
которым в 09:56 согласовали 4 990 ₽, в 13:15 получил счёт на 5 990 ₽ (диалог
142). Замечание ОП от 10 августа, 13:49: «И опять отправила способы оплаты, НО
уже со стоимостью 5990 (ранее было 4990), чего уже не нужно было делать».

Храним карту «название товара → названная цена». Понизить цену можно (уступка
при возражении перезаписывает запись), поднять — нельзя.

Revision ID: 045
Revises: 044
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "045"
down_revision: Union[str, None] = "044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialogs",
        sa.Column("quoted_prices", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dialogs", "quoted_prices")
