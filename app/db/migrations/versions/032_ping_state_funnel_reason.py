"""add funnel_reason to dialog_ping_states

detect_funnel_with_ai returns a one-sentence reason for the chosen funnel_type
(lead temperature). Persisting it on the ping state lets the chat UI show WHY the
ping funnel was picked next to the 🔔 Пинг badge, mirroring the AIRun reason fields.

Revision ID: 032
Revises: 031
Create Date: 2026-06-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialog_ping_states",
        sa.Column("funnel_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dialog_ping_states", "funnel_reason")
