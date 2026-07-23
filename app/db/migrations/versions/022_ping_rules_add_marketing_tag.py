"""add marketing_tag to ping_rules and dialog_ping_states

Revision ID: 022
Revises: 021
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ping_rules",
        sa.Column("marketing_tag", sa.String(64), nullable=True),
    )
    op.drop_constraint("uq_ping_rule_type_funnel_step", "ping_rules", type_="unique")
    op.create_unique_constraint(
        "uq_ping_rule_type_funnel_step_tag",
        "ping_rules",
        ["type_id", "funnel_type", "step", "marketing_tag"],
    )
    op.add_column(
        "dialog_ping_states",
        sa.Column("marketing_tag", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dialog_ping_states", "marketing_tag")
    op.drop_constraint("uq_ping_rule_type_funnel_step_tag", "ping_rules", type_="unique")
    op.create_unique_constraint(
        "uq_ping_rule_type_funnel_step",
        "ping_rules",
        ["type_id", "funnel_type", "step"],
    )
    op.drop_column("ping_rules", "marketing_tag")
