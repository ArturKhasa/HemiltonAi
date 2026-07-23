"""drop prompt_version from ai_runs

Revision ID: 009
Revises: 008
Create Date: 2026-05-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_runs DROP COLUMN IF EXISTS prompt_version")


def downgrade() -> None:
    op.add_column("ai_runs", sa.Column("prompt_version", sa.String(64), nullable=True))
