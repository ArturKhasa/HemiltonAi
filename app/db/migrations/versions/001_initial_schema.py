"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("users"):
        return

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("admin", "curator", "tester", name="userrole"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crm_client_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crm_client_id"),
    )

    op.create_table(
        "dialogs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("current_status", sa.Enum(
            "interested", "calculated", "hot", "waiting_prepayment",
            "order_created", "needs_curator", "lost", "no_response", "spam", "test",
            name="dialogstatus",
        ), nullable=False),
        sa.Column("assigned_curator_id", sa.Integer(), nullable=True),
        sa.Column("is_test", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["assigned_curator_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dialog_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Enum("client", "ai", "curator", "system", name="messagerole"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("external_message_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["dialog_id"], ["dialogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ai_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dialog_id", sa.Integer(), nullable=False),
        sa.Column("input_message_id", sa.Integer(), nullable=True),
        sa.Column("output_message_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(12, 6), nullable=True),
        sa.Column("cost_currency", sa.String(8), nullable=True),
        sa.Column("cost_estimated", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("need_curator", sa.Boolean(), nullable=True),
        sa.Column("curator_reason", sa.Text(), nullable=True),
        sa.Column("selected_script", sa.String(255), nullable=True),
        sa.Column("status_before", sa.String(64), nullable=True),
        sa.Column("status_after", sa.String(64), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["dialog_id"], ["dialogs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["input_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["output_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "scripts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("stage", sa.String(64), nullable=True),
        sa.Column("objection_type", sa.String(64), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version"),
    )

    op.create_index("ix_dialogs_status", "dialogs", ["current_status"])
    op.create_index("ix_dialogs_curator", "dialogs", ["assigned_curator_id"])
    op.create_index("ix_messages_dialog", "messages", ["dialog_id"])
    op.create_index("ix_ai_runs_dialog", "ai_runs", ["dialog_id"])


def downgrade() -> None:
    op.drop_table("prompt_versions")
    op.drop_table("scripts")
    op.drop_table("ai_runs")
    op.drop_table("messages")
    op.drop_table("dialogs")
    op.drop_table("clients")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS userrole")
    op.execute("DROP TYPE IF EXISTS dialogstatus")
    op.execute("DROP TYPE IF EXISTS messagerole")
    op.execute("DROP TYPE IF EXISTS dialogexamplelabel")
