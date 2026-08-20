"""dialogs.prior_history — переписка велась до нас

Сообщество подключают к ИИ, когда в нём уже годы переписок. Постоянный клиент
пишет «Давайте», продолжая вчерашний разговор, а ИИ видит его впервые и
начинает с «Меня зовут София» — и клиент понимает, что перед ним бот (диалог
756, 20 августа, в переписке 266 сообщений).

Флаг ставится один раз, когда диалог заводится у нас: по истории ВК видно, что
клиент писал раньше или что кто-то отвечал ему до нас. Такой диалог ИИ не
берёт; а если человек вернёт ИИ вручную, флаг останется — по нему видно, что
знакомиться заново нельзя.

Revision ID: 049
Revises: 048
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049"
down_revision: Union[str, None] = "048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialogs",
        sa.Column(
            "prior_history",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("dialogs", "prior_history")
