"""add status to ai_runs — record failed/timed-out runs

Revision ID: 036
Revises: 035
Create Date: 2026-07-14

Failed runs (timeout, parse error) are still billed by the provider, so they
must land in ai_runs or cost reporting undercounts real spend (~5-7% on qwen).
status: 'ok' | 'failed' | 'timeout'. Existing rows are all successful → 'ok'.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_runs",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
    )


def downgrade() -> None:
    op.drop_column("ai_runs", "status")
