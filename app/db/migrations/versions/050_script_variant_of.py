"""scripts.variant_of_script_id — «этот скрипт заменяет такой-то шаг»

Расчёт под рекламную метку заводят отдельным скриптом: «свитшот + жилетка,
8980 ₽» для метки, где в приветствии жилетки. Подставить его вместо общего
расчёта система умела только по дословно совпадающему условию — а условие
длинное, пишется руками, и совпадает оно примерно никогда. В итоге клиент с
жилетками получал «Стоимость толстовки — 5 990 ₽» (20 августа, диалог 731).

Теперь связь задаётся явно: в скрипте указывают, какой шаг он заменяет, и под
какой меткой. Связка воронки идёт по общему скрипту и на месте подменяет его
вариантом клиента.

Revision ID: 050
Revises: 049
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "050"
down_revision: Union[str, None] = "049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scripts",
        sa.Column("variant_of_script_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_scripts_variant_of_script_id",
        "scripts", "scripts",
        ["variant_of_script_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_scripts_variant_of_script_id", "scripts", type_="foreignkey")
    op.drop_column("scripts", "variant_of_script_id")
