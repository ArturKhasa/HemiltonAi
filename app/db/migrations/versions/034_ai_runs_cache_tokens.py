"""add cache_read_tokens / cache_write_tokens to ai_runs

Revision ID: 034
Revises: 033
Create Date: 2026-07-08

Prompt-cache token counts as reported by the provider, needed to audit and
recompute cost_amount (cached input is billed at a discounted rate). NULL means
the run predates cache tracking; 0 means tracked but nothing was cached.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_runs", sa.Column("cache_read_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_runs", sa.Column("cache_write_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_runs", "cache_write_tokens")
    op.drop_column("ai_runs", "cache_read_tokens")
