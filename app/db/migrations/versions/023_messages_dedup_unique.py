"""dedup messages by external_message_id and add unique index

Revision ID: 023
Revises: 022
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove existing duplicates: keep the earliest message per
    # (dialog_id, external_message_id), delete the rest.
    op.execute(
        """
        DELETE FROM messages
        WHERE external_message_id IS NOT NULL
          AND id NOT IN (
              SELECT MIN(id) FROM messages
              WHERE external_message_id IS NOT NULL
              GROUP BY dialog_id, external_message_id
          )
        """
    )
    # Partial unique index — only enforced for non-NULL external_message_id, so
    # manager/ping/AI messages (NULL) are unaffected.
    op.create_index(
        "uq_message_dialog_external_id",
        "messages",
        ["dialog_id", "external_message_id"],
        unique=True,
        postgresql_where=sa.text("external_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_message_dialog_external_id", table_name="messages")
