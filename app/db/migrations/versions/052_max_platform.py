"""vk_groups.platform — в таблице подключённых сообществ живут и боты MAX

Заказчик уводит трафик в MAX, и отвечать там должен тот же агент: те же
скрипты, пинги, статусы и очередь куратора. Заводить под это вторую таблицу
дорого не кодом, а связями: клиент привязан к сообществу через
`clients.vk_group_id`, и на этой привязке держатся пинги, панель, выгрузки,
фильтры чата и кэш вложений. Поэтому MAX-бот ложится строкой в ту же таблицу,
а платформу называет отдельная колонка:

- `platform='max'`, `group_id` — ID бота из `GET /me`;
- `access_token` — токен бота, `secret_key` — секрет вебхука
  (`X-Max-Bot-Api-Secret`);
- `confirmation_code` у MAX не нужен — подтверждения адреса там нет, поэтому
  колонка становится необязательной.

Уникальность ID переезжает на пару (платформа, ID): ID сообщества ВК и ID бота
MAX — числа из разных пространств, и совпадение между ними ничего не значит.

Revision ID: 052
Revises: 051
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "052"
down_revision: Union[str, None] = "051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vk_groups",
        sa.Column(
            "platform", sa.String(16), nullable=False, server_default="vk",
        ),
    )
    # Подписка на вебхук у MAX живёт на их стороне: её ставит и снимает
    # галочка «Активен». Флаг показывает в панели, дошло ли до MAX включение —
    # без него «активен» означал бы только запись в нашей базе.
    op.add_column(
        "vk_groups",
        sa.Column(
            "webhook_subscribed", sa.Boolean(), nullable=False, server_default=sa.false(),
        ),
    )
    # Публичное имя бота (@username) — по нему админ узнаёт бота в списке,
    # числовой ID ни о чём не говорит. Приходит из GET /me.
    op.add_column("vk_groups", sa.Column("username", sa.String(255), nullable=True))
    op.alter_column(
        "vk_groups", "confirmation_code",
        existing_type=sa.String(255), nullable=True,
    )

    # IF EXISTS: имя ограничения на боевой базе выдал сам постгрес при
    # `unique=True` (миграция 037), и падать здесь из-за него не за что.
    op.execute("ALTER TABLE vk_groups DROP CONSTRAINT IF EXISTS vk_groups_group_id_key")
    op.create_unique_constraint(
        "uq_vk_groups_platform_group", "vk_groups", ["platform", "group_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_vk_groups_platform_group", "vk_groups", type_="unique")
    op.create_unique_constraint("vk_groups_group_id_key", "vk_groups", ["group_id"])
    op.alter_column(
        "vk_groups", "confirmation_code",
        existing_type=sa.String(255), nullable=False,
    )
    op.drop_column("vk_groups", "username")
    op.drop_column("vk_groups", "webhook_subscribed")
    op.drop_column("vk_groups", "platform")
