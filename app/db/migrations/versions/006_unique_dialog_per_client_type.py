"""unique dialog per client type

Revision ID: 006
Revises: 005
Create Date: 2026-05-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep only the newest dialog per (client_id, type_id), delete older duplicates
    op.execute("""
        DELETE FROM dialogs
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM dialogs
            GROUP BY client_id, COALESCE(type_id, 1)
        )
    """)

    op.create_unique_constraint(
        "uq_dialog_client_type",
        "dialogs",
        ["client_id", "type_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_dialog_client_type", "dialogs", type_="unique")
