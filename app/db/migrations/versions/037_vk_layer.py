"""CRM-слой → VK-слой: vk_groups, клиенты по vk_user_id, локальные тексты фраз

Revision ID: 037
Revises: 036
Create Date: 2026-07-21

Система переходит с интеграции через CRM API на прямую работу с сообществами
ВКонтакте (Callback API + messages.send). Это отдельный продукт с чистой БД,
данные Monroe не мигрируются — колонки с CRM-данными удаляются без переноса:

- vk_groups: подключённые сообщества (токен/confirmation/secret в БД, не в env).
- clients: crm_client_id → (vk_group_id, vk_user_id), уникальная пара.
- dialogs: + ai_paused (живой оператор перехватил диалог), + vk_blocked
  (клиент запретил сообщения сообщества, ошибки ВК 901/902);
  − pull_crm_history (истории CRM больше нет, вся история локальная).
- scripts: crm_phrase_ids (ID фраз CRM) → phrase_text (готовый текст со spintax).
- ping_rules: phrase_ids → phrase_text.
- ai_runs: source_phrase_id → source_script_id (трейсинг использованного скрипта).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "037"
down_revision: Union[str, None] = "036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vk_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("confirmation_code", sa.String(length=255), nullable=False),
        sa.Column("secret_key", sa.String(length=255), nullable=True),
        sa.Column("dialog_type_id", sa.Integer(), sa.ForeignKey("dialog_types.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.drop_column("clients", "crm_client_id")
    op.add_column("clients", sa.Column("vk_user_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "clients",
        sa.Column("vk_group_id", sa.Integer(), sa.ForeignKey("vk_groups.id"), nullable=True),
    )
    op.create_unique_constraint("uq_client_vk_group_user", "clients", ["vk_group_id", "vk_user_id"])

    op.add_column(
        "dialogs",
        sa.Column("ai_paused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "dialogs",
        sa.Column("vk_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.drop_column("dialogs", "pull_crm_history")

    # Чистая БД нового продукта — контент не переносим, ID фраз CRM бессмысленны без CRM.
    op.drop_column("scripts", "crm_phrase_ids")
    op.add_column("scripts", sa.Column("phrase_text", sa.Text(), nullable=False, server_default=""))

    op.drop_column("ping_rules", "phrase_ids")
    op.add_column("ping_rules", sa.Column("phrase_text", sa.Text(), nullable=False, server_default=""))

    op.alter_column("ai_runs", "source_phrase_id", new_column_name="source_script_id")


def downgrade() -> None:
    op.alter_column("ai_runs", "source_script_id", new_column_name="source_phrase_id")

    op.drop_column("ping_rules", "phrase_text")
    op.add_column("ping_rules", sa.Column("phrase_ids", sa.Text(), nullable=False, server_default=""))

    op.drop_column("scripts", "phrase_text")
    op.add_column("scripts", sa.Column("crm_phrase_ids", sa.Text(), nullable=False, server_default=""))

    op.add_column(
        "dialogs",
        sa.Column("pull_crm_history", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.drop_column("dialogs", "vk_blocked")
    op.drop_column("dialogs", "ai_paused")

    op.drop_constraint("uq_client_vk_group_user", "clients", type_="unique")
    op.drop_column("clients", "vk_group_id")
    op.drop_column("clients", "vk_user_id")
    op.add_column("clients", sa.Column("crm_client_id", sa.String(length=255), nullable=True, unique=True))

    op.drop_table("vk_groups")
