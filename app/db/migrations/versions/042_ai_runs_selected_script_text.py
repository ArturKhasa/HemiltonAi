"""ai_runs.selected_script: varchar(255) -> text

Revision ID: 042
Revises: 041
Create Date: 2026-07-31

selected_script приходит от модели — она кладёт туда название или условие
применённого скрипта, длину которого мы не контролируем. Условия скриптов
редактируются в админке, и стоило одному из них перевалить за 255 символов, как
INSERT прогона падал с StringDataRightTruncationError, а клиент получал 500
вместо ответа (диалог 36 на проде, 31.07). Ограничение здесь ничего не защищало.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: Union[str, None] = "041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "ai_runs", "selected_script",
        existing_type=sa.String(length=255), type_=sa.Text(), existing_nullable=True,
    )


def downgrade() -> None:
    # Обрезаем то, что не влезет обратно, иначе ALTER не пройдёт.
    op.execute("UPDATE ai_runs SET selected_script = left(selected_script, 255)")
    op.alter_column(
        "ai_runs", "selected_script",
        existing_type=sa.Text(), type_=sa.String(length=255), existing_nullable=True,
    )
