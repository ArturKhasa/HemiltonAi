"""add ЧС status to dialog_statuses

Revision ID: 015
Revises: 014
Create Date: 2026-05-21
"""
from typing import Sequence, Union
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO dialog_statuses (name, pattern, is_active, created_at)
        VALUES ('ЧС', 'Клиент запретил сообщения от сообщества', true, NOW())
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM dialog_statuses WHERE name = 'ЧС'")
