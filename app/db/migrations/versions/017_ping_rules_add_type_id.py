"""add type_id to ping_rules

Revision ID: 017
Revises: 016
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ping_rules",
        sa.Column("type_id", sa.Integer, sa.ForeignKey("dialog_types.id"), nullable=True, server_default="1"),
    )
    op.drop_constraint("uq_ping_rule_funnel_step", "ping_rules", type_="unique")
    op.create_unique_constraint(
        "uq_ping_rule_type_funnel_step", "ping_rules", ["type_id", "funnel_type", "step"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_ping_rule_type_funnel_step", "ping_rules", type_="unique")
    op.drop_column("ping_rules", "type_id")
    op.create_unique_constraint("uq_ping_rule_funnel_step", "ping_rules", ["funnel_type", "step"])
