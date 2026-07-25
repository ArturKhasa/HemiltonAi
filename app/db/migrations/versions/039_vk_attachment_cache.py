"""add vk_attachment_cache (перезаливка чужих фото на своё сообщество)

Revision ID: 039
Revises: 038
Create Date: 2026-07-24

VK принимает attachment в messages.send только на объекты, принадлежащие токену
отправителя. Ссылки на фото из внешних источников (Wazzup24, товарная матрица)
скачиваются и перезаливаются через photos.getMessagesUploadServer один раз на
сообщество, результат кэшируется здесь по (vk_group_id, source_url).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vk_attachment_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vk_group_id", sa.Integer(), sa.ForeignKey("vk_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("attachment", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_attachment_cache_group_url", "vk_attachment_cache", ["vk_group_id", "source_url"],
    )


def downgrade() -> None:
    op.drop_table("vk_attachment_cache")
