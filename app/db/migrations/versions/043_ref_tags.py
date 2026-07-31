"""ref_tags — метки рекламных ссылок, на которые отвечает ИИ

Revision ID: 043
Revises: 042
Create Date: 2026-08-01

Заказчик: «надо сделать админку, где указываются реф метки, на которые ИИ будет
отвечать» — их проставляют и редактируют постоянно, и раньше это требовало
правки скриптов руками.

Метка приезжает в ссылке вида ?ref=adb_r&ref_source=rusover449 — кампания во
втором параметре. К метке привязывается приветствие, чтобы клиент с конкретной
рекламы получал своё первое сообщение, а не дефолтное.

ВАЖНО: пока таблица пуста, белый список НЕ применяется и ИИ отвечает всем, как
раньше. Иначе первая же миграция на проде оборвала бы все живые диалоги.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: Union[str, None] = "042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ref_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("dialog_types.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tag", sa.String(128), nullable=False),
        # ИИ отвечает клиентам с этой метки. Снятая галка = трафик ведёт человек.
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        # Приветствие для этой кампании. NULL — берётся общее правило подбора.
        sa.Column("greeting_script_id", sa.Integer(), sa.ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("type_id", "tag", name="uq_ref_tag_type_tag"),
    )
    op.create_index("ix_ref_tags_tag", "ref_tags", ["tag"])


def downgrade() -> None:
    op.drop_index("ix_ref_tags_tag", table_name="ref_tags")
    op.drop_table("ref_tags")
