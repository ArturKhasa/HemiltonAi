"""users.name — имя менеджера для панели

27.08 ОП завела десять аккаунтов кураторов: hemilton1@mail.ru … hemilton10@mail.ru.
По ним же теперь назначается ответственный за диалог, и в списке лидов вместо
живого человека стояло бы «hemilton7@mail.ru» — по такой подписи менеджер своего
клиента не найдёт, а именно ради этого ответственного и заводили («менеджеры же
не будут каждого своего по имени искать», Лена, 25.08).

Колонка необязательная: не заполнили — в панели показываем часть адреса до «@»,
как и было.

Revision ID: 055
Revises: 054
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "055"
down_revision: Union[str, None] = "054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "name")
