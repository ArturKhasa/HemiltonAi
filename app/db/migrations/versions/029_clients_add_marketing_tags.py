"""add marketing_tags to clients

Revision ID: 029
Revises: 028
Create Date: 2026-06-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("marketing_tags", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clients", "marketing_tags")
