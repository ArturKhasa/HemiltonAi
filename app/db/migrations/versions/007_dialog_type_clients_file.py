"""add successful_clients_file to dialog_types

Revision ID: 007
Revises: 006
Create Date: 2026-05-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialog_types",
        sa.Column("successful_clients_file", sa.String(512), nullable=True),
    )
    op.execute(
        "UPDATE dialog_types SET successful_clients_file = 'data/successful_clients.txt' WHERE name = 'monroe_book'"
    )


def downgrade() -> None:
    op.drop_column("dialog_types", "successful_clients_file")
