"""add full_context to ai_runs

Revision ID: 025
Revises: 024
Create Date: 2026-06-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_runs", sa.Column("full_context", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_runs", "full_context")
