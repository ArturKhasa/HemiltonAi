"""Возврат диалога ИИ и воронки пингов для горячих лидов

Три правки ОП от 01.09:

* `dialog_ping_states.resumed_by_manager` — менеджер снял паузу и вернул диалог
  автоматике. Пока признак стоит, воронка не гасится заслоном горячей стадии:
  человек уже видел диалог и отдал его обратно осознанно («ИИ нужно продолжить
  пинговать лида вне зависимости от статуса/прошлого диалога»).
* воронка `checkout` — клиент увидел способы оплаты и замолчал. Просьба Лены
  дословно: «Нужно сделать новую воронку пингов для лидов, которые молчат после
  способов оплаты, сами пинги добавлю сама».
* воронка `after_payment` — счёт выставлен, предоплаты нет. В коде она
  вызывалась с 27.08 (`app.sales.status_flow`), но правил под неё в базе не было
  ни одного, и вызов молча выходил по «no rules».

Шаги заводятся **выключенными**. Тексты пишет ОП («сами пинги добавлю сама»,
Лена 01.09), а до этого воронка молчит: выключенный шаг не выбирается ни
воронкой, ни агентом, и клиенту не уходит ничего. В панели («Правила пингов»)
шаги при этом видны — их правят и включают галочкой «Активно». Каркас нужен,
чтобы правки было куда вносить: пустая воронка в интерфейсе не показывается
вовсе.

Revision ID: 056
Revises: 055
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "056"
down_revision: Union[str, None] = "055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Шаг: (воронка, номер, задержка в секундах, текст).
# Задержки короче, чем у общей воронки «знает цену»: лид уже горячий, сутки
# молчания на этом шаге стоят дороже. Тексты — заготовка под правку ОП, шаги
# заводятся выключенными и до включения клиенту не уходят.
_SEED: tuple[tuple[str, int, int, str], ...] = (
    (
        "checkout", 1, 30 * 60,
        "[Имя], подскажите, получилось выбрать удобный способ оплаты?\n\n"
        "Если что-то смущает - скажите, подберём вариант.",
    ),
    (
        "checkout", 2, 3 * 3600,
        "Место в производстве пока держу за Вами)\n\n"
        "Подскажите, по оформлению остались вопросы? Отвечу на любые.",
    ),
    (
        "checkout", 3, 24 * 3600,
        "[Имя], Ваш заказ пока не оформлен.\n\n"
        "Скажите, продолжаем? Если удобнее обсудить голосом - напишите, "
        "менеджер свяжется с Вами.",
    ),
    (
        "checkout", 4, 48 * 3600,
        "[Имя], подскажите, заказ ещё актуален?\n\n"
        "Если планы поменялись - просто напишите, и я не буду больше беспокоить.",
    ),
    (
        "after_payment", 1, 3600,
        "[Имя], подскажите, получилось внести предоплату?\n\n"
        "Если ссылка не открывается - пришлю заново.",
    ),
    (
        "after_payment", 2, 6 * 3600,
        "Заказ держу за Вами) Как только пройдёт предоплата, передаю его "
        "дизайнеру - макет покажем Вам до запуска в работу.",
    ),
    (
        "after_payment", 3, 24 * 3600,
        "[Имя], предоплата пока не поступила.\n\n"
        "Подскажите, заказ актуален? Если нужно больше времени - скажите, "
        "сколько, и я подожду.",
    ),
)


def upgrade() -> None:
    op.add_column(
        "dialog_ping_states",
        sa.Column(
            "resumed_by_manager",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    conn = op.get_bind()
    # type_id: тип диалога в проде один («hemilton», id=1), но брать его надо из
    # базы — на dev-стенде нумерация своя.
    type_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM dialog_types ORDER BY id"))]
    for type_id in type_ids:
        for funnel, step, delay, text in _SEED:
            exists = conn.execute(
                sa.text(
                    "SELECT 1 FROM ping_rules WHERE type_id = :t AND funnel_type = :f "
                    "AND step = :s AND marketing_tag IS NULL"
                ),
                {"t": type_id, "f": funnel, "s": step},
            ).first()
            if exists:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO ping_rules (type_id, funnel_type, step, delay_seconds, "
                    "phrase_text, is_active) VALUES (:t, :f, :s, :d, :p, false)"
                ),
                {"t": type_id, "f": funnel, "s": step, "d": delay, "p": text},
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM ping_rules WHERE funnel_type IN ('checkout', 'after_payment')")
    )
    op.drop_column("dialog_ping_states", "resumed_by_manager")
