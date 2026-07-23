"""strip leading «#» from dialog_ping_states.marketing_tag

Ping rules were reseeded with tags without «#», but existing ping states still
hold the old «#»-prefixed value. Exact-match lookups (_find_rule, get_ping_scripts)
would then miss tag-specific rules and silently fall back to NULL rules.

Revision ID: 027
Revises: 026
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE dialog_ping_states "
        "SET marketing_tag = ltrim(marketing_tag, '#') "
        "WHERE marketing_tag LIKE '#%'"
    )


def downgrade() -> None:
    # No reliable reverse: original «#» prefix is lost intentionally.
    pass
