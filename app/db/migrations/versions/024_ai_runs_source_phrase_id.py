"""add source_phrase_id to ai_runs

Revision ID: 024
Revises: 023
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_runs", sa.Column("source_phrase_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_runs", "source_phrase_id")
