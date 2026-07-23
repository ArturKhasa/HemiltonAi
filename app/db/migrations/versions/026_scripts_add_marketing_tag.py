"""add marketing_tag to scripts

Revision ID: 026
Revises: 025
Create Date: 2026-06-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scripts",
        sa.Column("marketing_tag", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scripts", "marketing_tag")
