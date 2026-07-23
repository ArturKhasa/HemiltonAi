"""feedback add is_ping column

Revision ID: 021
Revises: 020
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("message_feedbacks", sa.Column("is_ping", sa.Boolean(), nullable=False, server_default="false"))
    op.drop_index("ix_message_feedbacks_type_id_is_active", table_name="message_feedbacks")
    op.create_index("ix_message_feedbacks_type_id_is_ping_is_active", "message_feedbacks", ["type_id", "is_ping", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_message_feedbacks_type_id_is_ping_is_active", table_name="message_feedbacks")
    op.create_index("ix_message_feedbacks_type_id_is_active", "message_feedbacks", ["type_id", "is_active"])
    op.drop_column("message_feedbacks", "is_ping")
