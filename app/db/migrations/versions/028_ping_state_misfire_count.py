"""add misfire_count to dialog_ping_states

The ping agent (haiku) sometimes returns action=complete WITHOUT calling its
context tools — a model misfire, not a real "stop". The worker used to treat any
complete as terminal, permanently killing the ping sequence. We now retry such
misfires; misfire_count bounds the retries so a persistently-broken agent can't
loop forever.

Revision ID: 028
Revises: 027
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialog_ping_states",
        sa.Column("misfire_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("dialog_ping_states", "misfire_count")
