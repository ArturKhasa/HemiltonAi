"""add ai_provider to dialogs

Revision ID: 011
Revises: 010
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialogs",
        sa.Column("ai_provider", sa.String(32), nullable=False, server_default="openai"),
    )


def downgrade() -> None:
    op.drop_column("dialogs", "ai_provider")
