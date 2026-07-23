"""add dialog types

Revision ID: 005
Revises: 004
Create Date: 2026-05-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dialog_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.execute(
        "INSERT INTO dialog_types (id, name, display_name, is_active, created_at) "
        "VALUES (1, 'monroe_book', 'Monroe Book', true, NOW())"
    )

    op.add_column(
        "dialogs",
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("dialog_types.id"), nullable=True, server_default="1"),
    )
    op.add_column(
        "scripts",
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("dialog_types.id"), nullable=True, server_default="1"),
    )
    op.add_column(
        "prompt_versions",
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("dialog_types.id"), nullable=True, server_default="1"),
    )

    op.execute("UPDATE dialogs SET type_id = 1 WHERE type_id IS NULL")
    op.execute("UPDATE scripts SET type_id = 1 WHERE type_id IS NULL")
    op.execute("UPDATE prompt_versions SET type_id = 1 WHERE type_id IS NULL")

    op.drop_constraint("prompt_versions_name_version_key", "prompt_versions", type_="unique")
    op.create_unique_constraint(
        "uq_prompt_versions_type_name_version",
        "prompt_versions",
        ["type_id", "name", "version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_prompt_versions_type_name_version", "prompt_versions", type_="unique")
    op.create_unique_constraint("prompt_versions_name_version_key", "prompt_versions", ["name", "version"])

    op.drop_column("prompt_versions", "type_id")
    op.drop_column("scripts", "type_id")
    op.drop_column("dialogs", "type_id")

    op.drop_table("dialog_types")
