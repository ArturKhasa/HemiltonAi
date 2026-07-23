"""add updated_at to ping_rules

Revision ID: 014
Revises: 013
Create Date: 2026-05-20
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ping_rules",
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ping_rules", "updated_at")
