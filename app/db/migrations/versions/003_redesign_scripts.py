"""redesign scripts table — condition + crm_phrase_id only

Revision ID: 003
Revises: 002
Create Date: 2026-05-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scripts", sa.Column("condition", sa.Text(), nullable=True))

    op.execute("UPDATE scripts SET condition = COALESCE(body, name)")
    op.execute("UPDATE scripts SET crm_phrase_id = 0 WHERE crm_phrase_id IS NULL")

    op.alter_column("scripts", "condition", nullable=False)
    op.alter_column("scripts", "crm_phrase_id", nullable=False)

    op.drop_column("scripts", "category")
    op.drop_column("scripts", "stage")
    op.drop_column("scripts", "objection_type")
    op.drop_column("scripts", "body")


def downgrade() -> None:
    op.add_column("scripts", sa.Column("body", sa.Text(), nullable=True))
    op.add_column("scripts", sa.Column("objection_type", sa.String(64), nullable=True))
    op.add_column("scripts", sa.Column("stage", sa.String(64), nullable=True))
    op.add_column("scripts", sa.Column("category", sa.String(64), nullable=True))
    op.execute("UPDATE scripts SET body = condition")
    op.drop_column("scripts", "condition")
