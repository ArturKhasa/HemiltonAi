"""drop crm_dialog_id from dialogs

Revision ID: 010
Revises: 009
Create Date: 2026-05-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE dialogs DROP CONSTRAINT IF EXISTS dialogs_crm_dialog_id_key")
    op.execute("ALTER TABLE dialogs DROP COLUMN IF EXISTS crm_dialog_id")


def downgrade() -> None:
    op.add_column("dialogs", sa.Column("crm_dialog_id", sa.String(255), nullable=True))
    op.create_unique_constraint("dialogs_crm_dialog_id_key", "dialogs", ["crm_dialog_id"])
