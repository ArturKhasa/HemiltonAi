"""crm_phrase_id int -> crm_phrase_ids text (comma-separated)

Revision ID: 004
Revises: 003
Create Date: 2026-05-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scripts", sa.Column("crm_phrase_ids", sa.Text(), nullable=True))
    op.execute("UPDATE scripts SET crm_phrase_ids = crm_phrase_id::TEXT")
    op.alter_column("scripts", "crm_phrase_ids", nullable=False)
    op.drop_column("scripts", "crm_phrase_id")
    op.drop_constraint("scripts_name_key", "scripts", type_="unique")
    op.drop_column("scripts", "name")


def downgrade() -> None:
    op.add_column("scripts", sa.Column("name", sa.String(255), nullable=True))
    op.create_unique_constraint("scripts_name_key", "scripts", ["name"])
    op.add_column("scripts", sa.Column("crm_phrase_id", sa.Integer(), nullable=True))
    op.execute("UPDATE scripts SET crm_phrase_id = SPLIT_PART(crm_phrase_ids, ',', 1)::INTEGER")
    op.alter_column("scripts", "crm_phrase_id", nullable=False)
    op.drop_column("scripts", "crm_phrase_ids")
