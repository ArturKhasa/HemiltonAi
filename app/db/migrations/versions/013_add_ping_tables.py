"""add ping_rules and dialog_ping_states tables

Revision ID: 013
Revises: 012
Create Date: 2026-05-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ping_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("funnel_type", sa.String(32), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("delay_seconds", sa.Integer(), nullable=False),
        sa.Column("phrase_ids", sa.Text(), nullable=False, server_default=""),
        sa.Column("manual_text", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("funnel_type", "step", name="uq_ping_rule_funnel_step"),
    )

    op.create_table(
        "dialog_ping_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "dialog_id",
            sa.Integer(),
            sa.ForeignKey("dialogs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("funnel_type", sa.String(32), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_ping_sent_at", sa.DateTime(), nullable=True),
        sa.Column("next_ping_due_at", sa.DateTime(), nullable=True),
        sa.Column("is_completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_index("ix_dialog_ping_states_next_due", "dialog_ping_states", ["next_ping_due_at"])


def downgrade() -> None:
    op.drop_table("dialog_ping_states")
    op.drop_table("ping_rules")
