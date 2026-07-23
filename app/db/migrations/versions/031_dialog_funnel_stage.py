"""add funnel_stage to dialogs

FunnelAgent detects the sales-script stage (greeting/format/calculation/timing/
photo/contacts/prepayment/paid) on every client message, before SalesAgent runs.
The stage is orthogonal to funnel_type (lead temperature) and CRM status; both the
SalesAgent and the async PingAgent read dialogs.funnel_stage to ground their behavior.

Revision ID: 031
Revises: 030
Create Date: 2026-06-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialogs",
        sa.Column("funnel_stage", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dialogs", "funnel_stage")
