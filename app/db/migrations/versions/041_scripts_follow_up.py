"""scripts.follow_up_script_id — скрипт, уходящий сразу следом за этим

Revision ID: 041
Revises: 040
Create Date: 2026-07-30

Регламент ОП описывает связки прямо в условии скрипта: у «1.2 Вопрос после
приветствия» условие звучит как «Отправляем сразу после первого скрипта с
приветствием, чтобы продолжить диалог с клиентом». Само приветствие вопросом не
заканчивается, поэтому агент, отдающий за ход ровно одну реплику, оставлял
диалог висеть, пока клиент не напишет сам.

Ссылка на следующий скрипт хранится данными, а не хардкодом по названию, —
связки настраиваются в админке и работают на любом шаге воронки.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scripts",
        sa.Column("follow_up_script_id", sa.Integer(), nullable=True),
    )
    # SET NULL, а не CASCADE: удаление второго скрипта связки не должно уносить
    # приветствие — связка просто перестаёт действовать.
    op.create_foreign_key(
        "fk_scripts_follow_up_script_id",
        "scripts", "scripts",
        ["follow_up_script_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_scripts_follow_up_script_id", "scripts", type_="foreignkey")
    op.drop_column("scripts", "follow_up_script_id")
