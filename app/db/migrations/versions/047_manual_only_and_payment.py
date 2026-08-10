"""scripts.manual_only и dialogs.payment_confirmed_at

Два шага воронки ИИ делал сам, хотя не имел права.

1. «Ваш макет готов! Проверьте, пожалуйста, все ли верно?» — скрипт 465. ОП (10
   августа, 14:15): «Макет на правки всегда отправляем дизам, они вручную кидают
   его с таким скриптом». У скрипта не было ни стадии, ни признака ручной
   отправки, поэтому он был виден модели всегда — и ушёл клиенту без макета
   (диалог 142, 14:13).

2. «Благодарю Вас за заказ и за доверие! Теперь пришлите адрес пункта выдачи
   СДЭК» — скрипт 384 стадии post_payment, плюс статус «Заказ оформлен». ОП, там
   же: «Оплаты от клиента не было». Гейта на подтверждённую оплату не
   существовало вовсе.

Revision ID: 047
Revises: 046
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scripts",
        sa.Column(
            "manual_only", sa.Boolean(), nullable=False, server_default=sa.text("false"),
        ),
    )
    op.add_column("dialogs", sa.Column("payment_confirmed_at", sa.DateTime(), nullable=True))

    # Скрипт отправки макета — единственный, о котором ОП сказал прямо.
    # Остальные заказчик размечает в админке (вопрос В1 плана).
    op.execute(
        "UPDATE scripts SET manual_only = true "
        "WHERE condition ILIKE '%макет готов%'"
    )


def downgrade() -> None:
    op.drop_column("dialogs", "payment_confirmed_at")
    op.drop_column("scripts", "manual_only")
