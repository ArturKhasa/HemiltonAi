"""user_dialog_types — доступ кураторов к направлениям

Revision ID: 035
Revises: 034
Create Date: 2026-07-08

Many-to-many пользователь <-> dialog_type. Куратор видит только диалоги
привязанных направлений; админ видит всё независимо от записей.
Бэкфилл: все существующие пользователи получают все направления, чтобы
никто не потерял доступ при выкатке.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_dialog_types",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("dialog_types.id", ondelete="CASCADE"), primary_key=True),
    )
    op.execute(
        """
        INSERT INTO user_dialog_types (user_id, type_id)
        SELECT u.id, dt.id FROM users u CROSS JOIN dialog_types dt
        """
    )


def downgrade() -> None:
    op.drop_table("user_dialog_types")
