"""clients.max_chat_id — по нему читается история диалога в MAX

Об исходящих бота MAX вебхук не присылает ничего: `message_created` приходит
только о входящих. А пишет от имени бота не только эта панель — к боту
подключён Wazzup, из которого отвечают менеджеры ОП. Их реплики не попадали ни
в панель, ни в паузу ИИ (ОП, 27.08: «через бс клиенту ответила 4 мин назад, в
панели мои сообщения не отобразились еще, как будто все так же ии работает»).

Единственный способ увидеть их — читать историю самим, а `GET /messages` берёт
только `chat_id`: по `user_id` API отвечает отказом, список личных чатов бота
пуст. Приходит chat_id во входящем событии (`recipient.chat_id`) — эта колонка
его и хранит. Старым карточкам значение восстанавливается из идентификатора
любого их сообщения (см. app.max.manager_watch.chat_id_from_mid).

Revision ID: 053
Revises: 052
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "053"
down_revision: Union[str, None] = "052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("max_chat_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "max_chat_id")
