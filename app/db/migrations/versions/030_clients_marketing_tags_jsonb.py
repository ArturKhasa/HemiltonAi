"""convert clients.marketing_tags json -> jsonb

json stores the text as-is (escaped \\uXXXX from json.dumps); jsonb stores parsed
Unicode and renders readable Cyrillic.

Revision ID: 030
Revises: 029
Create Date: 2026-06-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE clients "
        "ALTER COLUMN marketing_tags TYPE jsonb USING marketing_tags::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE clients "
        "ALTER COLUMN marketing_tags TYPE json USING marketing_tags::json"
    )
