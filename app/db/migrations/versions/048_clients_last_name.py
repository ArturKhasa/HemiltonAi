"""clients.last_name — фамилия клиента из профиля ВК

В списке лидов первой строкой стоял числовой VK ID, а имя пряталось строкой ниже
серым. ОП: «имя фамилия надо вывести в лидах вместо айди» (10 августа, 16:16).

Фамилия хранится отдельно от `clients.name` намеренно: `name` — это форма
обращения к клиенту в диалоге, и обращаться по фамилии нельзя («Соколова,
здравствуйте» звучит как повестка, см. app.utils.text.usable_name). Полное имя
собирается только для интерфейса.

Revision ID: 048
Revises: 047
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("last_name", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "last_name")
