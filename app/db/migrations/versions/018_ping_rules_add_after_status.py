"""add after_status to ping_rules

Revision ID: 018
Revises: 017
Create Date: 2026-06-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ping_rules",
        sa.Column("after_status", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ping_rules", "after_status")
