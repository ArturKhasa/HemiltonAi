"""add dialog_statuses table and migrate current_status column

Revision ID: 012
Revises: 011
Create Date: 2026-05-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create dialog_statuses table
    op.create_table(
        "dialog_statuses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    # 2. Insert default statuses
    op.execute(
        """
        INSERT INTO dialog_statuses (name, pattern, is_active, created_at) VALUES
        ('Поинтересовался',  'Клиент написал впервые: приветствие, выбор формата, идёт этап расчёта стоимости',                                                    true, NOW()),
        ('Есть расчет',      'Расчёт стоимости отправлен клиенту, ожидаем его реакцию и решение',                                                                  true, NOW()),
        ('Горячий',          'Клиент подтвердил интерес после расчёта: запрашиваем фото объекта/замеров, уточняем сроки и детали, переходим к оформлению заказа',   true, NOW()),
        ('Ждем предоплату',  'Ссылка на оплату или реквизиты отправлены клиенту, ожидаем поступления предоплаты',                                                   true, NOW()),
        ('Заказ оформлен',   'Клиент внёс первую предоплату',                                                                      true, NOW()),
        ('Нужен куратор',    'Ситуация требует вмешательства живого специалиста',                                                                                    true, NOW()),
        ('Спам',             'Сообщение является спамом или нецелевым обращением',                                                                                   true, NOW())
        """
    )


    # 3. Add current_status_id column to dialogs (nullable FK)
    op.add_column(
        "dialogs",
        sa.Column("current_status_id", sa.Integer(), sa.ForeignKey("dialog_statuses.id"), nullable=True),
    )

    # 4. Migrate existing data from old current_status enum to new FK
    op.execute(
        """
        UPDATE dialogs SET current_status_id = (
            SELECT id FROM dialog_statuses WHERE name = CASE dialogs.current_status::text
                WHEN 'interested'         THEN 'Поинтересовался'
                WHEN 'calculated'         THEN 'Есть расчет'
                WHEN 'hot'                THEN 'Горячий'
                WHEN 'waiting_prepayment' THEN 'Ждем предоплату'
                WHEN 'order_created'      THEN 'Заказ оформлен'
                WHEN 'needs_curator'      THEN 'Нужен куратор'
                WHEN 'lost'               THEN 'Потерян'
                WHEN 'no_response'        THEN 'Нет ответа'
                WHEN 'spam'               THEN 'Спам'
                ELSE NULL
            END
        )
        """
    )

    # 5. Drop old current_status column from dialogs
    op.drop_column("dialogs", "current_status")

    # 6. Drop the PostgreSQL enum type
    op.execute("DROP TYPE IF EXISTS dialogstatus")


def downgrade() -> None:
    # Re-create the enum type
    op.execute(
        "CREATE TYPE dialogstatus AS ENUM ('interested','calculated','hot','waiting_prepayment','order_created','needs_curator','lost','no_response','spam','test')"
    )

    # Add back the old current_status column with a default
    op.add_column(
        "dialogs",
        sa.Column(
            "current_status",
            sa.Enum(
                "interested", "calculated", "hot", "waiting_prepayment",
                "order_created", "needs_curator", "lost", "no_response", "spam", "test",
                name="dialogstatus",
            ),
            nullable=True,
        ),
    )

    # Restore data from FK back to enum
    op.execute(
        """
        UPDATE dialogs SET current_status = CASE (SELECT name FROM dialog_statuses WHERE id = dialogs.current_status_id)
            WHEN 'Заинтересован'       THEN 'interested'
            WHEN 'Просчитан'           THEN 'calculated'
            WHEN 'Горячий'             THEN 'hot'
            WHEN 'Ожидание предоплаты' THEN 'waiting_prepayment'
            WHEN 'Заказ создан'        THEN 'order_created'
            WHEN 'Нужен куратор'       THEN 'needs_curator'
            WHEN 'Потерян'             THEN 'lost'
            WHEN 'Нет ответа'          THEN 'no_response'
            WHEN 'Спам'                THEN 'spam'
            ELSE NULL
        END::dialogstatus
        """
    )

    # Drop FK column
    op.drop_column("dialogs", "current_status_id")

    # Drop dialog_statuses table
    op.drop_table("dialog_statuses")
