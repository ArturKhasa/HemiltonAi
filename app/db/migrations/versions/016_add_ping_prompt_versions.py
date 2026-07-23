"""add ping_prompt_versions table

Revision ID: 016
Revises: 015
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ping_prompt_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("type_id", sa.Integer, sa.ForeignKey("dialog_types.id"), nullable=True, server_default="1"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("type_id", "name", "version", name="uq_ping_prompt_type_name_version"),
    )


def downgrade() -> None:
    op.drop_table("ping_prompt_versions")
