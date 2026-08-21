"""scripts.is_pair_variant — «этот вариант шага для заказа на двоих»

Клиент отвечает на вопрос про надпись двумя именами — «Шишкин Кирилл и Виктория
Шишкина», — и это заказ на два изделия (правило ОП от 21.08). Расчёт ему всё
равно уходил на одно, и в оформлении стояла сумма 5 990 ₽ за два свитшота
(диалог 75853).

Парный расчёт заводят отдельным скриптом — так же, как расчёт под рекламную
метку: в скрипте указано, какой шаг он заменяет (`variant_of_script_id`,
миграция 050), а этот флаг говорит, что заменяет он его не под метку, а для
заказа на двоих.

Revision ID: 051
Revises: 050
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "051"
down_revision: Union[str, None] = "050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scripts",
        sa.Column(
            "is_pair_variant", sa.Boolean(), nullable=False, server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("scripts", "is_pair_variant")
