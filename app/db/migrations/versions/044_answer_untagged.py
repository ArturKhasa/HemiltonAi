"""dialog_types.answer_untagged — отвечать ли клиентам без ref-метки

Revision ID: 044
Revises: 043
Create Date: 2026-08-01

Белый список меток (миграция 043) по букве требования блокирует всё, чего в нём
нет, — включая приход вообще без метки. Но ВК присылает ref только в ПЕРВОМ
сообщении, поэтому без метки приходят и живые клиенты: зашедшие в группу через
поиск, перешедшие по ссылке без параметров, писавшие раньше, и те, чьё первое
сообщение до вебхука не долетело.

Флаг разводит два случая: чужая реклама (метка есть, но не в списке) блокируется
всегда, а приход без метки обслуживается или нет — по решению отдела продаж.
Значение по умолчанию — отвечать, чтобы органика не терялась молча.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialog_types",
        sa.Column("answer_untagged", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("dialog_types", "answer_untagged")
