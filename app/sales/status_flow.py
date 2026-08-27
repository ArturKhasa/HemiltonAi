"""Статус диалога считает код по фактам, а не модель по ощущению.

Ступень ставится, только когда факт подтверждён ДОСТАВЛЕННЫМ сообщением: не
«модель решила отправить цену», а «клиент её увидел». Отметка в базе для этого
не годится — на ней уже обжигались (диалог 78880, 24.08: сумму за диалогом
закрепили, а сообщение со связкой не доехало, и следующий ход отправил похвалу
с доставкой без единой цифры).

Детекторы взяты те же, по которым воронка и так принимает решения, — новой
эвристики здесь нет:

| Ступень          | Факт                          | Чем проверяем                       |
|------------------|-------------------------------|-------------------------------------|
| Есть расчет      | сумма дошла до клиента        | `prices_in` по доставленным нашим   |
| Уточняем детали  | клиент ответил после расчёта  | `collect_slots`: город, цвет, размер|
| Горячий          | показаны способы оплаты       | `CHECKOUT_PRESENTED_RE`             |
| Ждем данные      | запрошены ФИО и телефон       | `ASKS_CONTACTS_RE`                  |
| Ждем предоплату  | ушла ссылка на оплату         | `PAYMENT_LINK_RE`                   |
| Заказ оформлен   | оплату подтвердил человек     | `dialogs.payment_confirmed_at`      |

Читаем и сообщения менеджера: 665 диалогов ведёт живой оператор при выключенном
ИИ, и статусы им нужны ровно так же. Узнаётся при этом текст скрипта — свободный
пересказ менеджера регулярка не увидит, и это осознанное ограничение.

А вот массовые рассылки не читаем совсем. Они лежат в тех же строках с ролью
`curator` (637 807 сообщений из 667 561), и цена в них — обычное дело:
«ТОЛСТОВКА ЗА 4 990₽ + 3 ПОДАРКА» ушла в 58 238 диалогов, «300 руб. — и скидка
25 %» в 73 716. Без этого различия расчётом считался бы каждый, кому пришло
рекламное письмо. Рассылку помечает вебхук (`app.vk.broadcast.is_broadcast`), на
старых записях пометку расставляет `python -m app.commands.mark_broadcasts`.

Пометка ловит не всё: у персонализированной рассылки имя стоит и в середине
(«⏰ Андрей, осталась всего неделя… Один свитшот — 4 790 руб.»), и по тексту она
от менеджерской реплики не отличается. Поэтому второе правило — реплики
менеджера считаются шагом воронки только в диалогах, где клиент написал хоть
слово. Диалог 383 состоит из двенадцати рекламных писем и ни одного сообщения
клиента: отвечать там некому, и расчётом это не является.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dialog, DialogStatusConfig, Message, MessageRole
from app.sales.funnel_steps import ASKS_CONTACTS_RE, CHECKOUT_PRESENTED_RE, PAYMENT_LINK_RE
from app.sales.order_slots import collect_slots
from app.sales.prices import prices_in
from app.sales.status_names import (
    AWAITING_DATA,
    AWAITING_PREPAY,
    CALCULATED,
    CLARIFYING,
    HOT,
    INTERESTED,
    ORDER_CREATED,
    SIDE_STATUSES,
    is_ladder,
    rank,
)
from app.vk.outgoing import was_delivered

logger = logging.getLogger(__name__)

# Слоты, которые клиент называет уже ПОСЛЕ расчёта: город доставки в первую
# очередь (о нём и спрашивает связка вслед за ценой), а также цвет и размер —
# ими начинается «Уточняем детали» по описанию ОП.
_CLARIFYING_SLOTS = ("city", "color", "size")


async def earned_status(db: AsyncSession, dialog: Dialog) -> str:
    """Самая дальняя ступень, факт которой подтверждён перепиской.

    Возвращает всегда имя ступени: диалог существует — значит клиент как минимум
    поинтересовался.
    """
    # Оплату подтверждает человек кнопкой в панели, переписке тут верить нечему.
    if dialog.payment_confirmed_at is not None:
        return ORDER_CREATED

    messages = list((await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog.id)
        .order_by(Message.created_at, Message.id)
    )).scalars().all())

    # Рассылка приходит и в диалоги, где клиент не написал ни слова: такой диалог
    # состоит из одних рекламных писем, и отвечать в нём некому. Сообщения
    # менеджера считаем шагом воронки только там, где клиент заговорил.
    client_spoke = any(m.role == MessageRole.client for m in messages)

    ours = [
        m.text or "" for m in messages
        if was_delivered(m)
        and not (m.msg_metadata or {}).get("broadcast")
        and (
            m.role == MessageRole.ai
            or (m.role == MessageRole.curator and client_spoke)
        )
    ]

    if any(PAYMENT_LINK_RE.search(t) for t in ours):
        return AWAITING_PREPAY
    if any(ASKS_CONTACTS_RE.search(t) for t in ours):
        return AWAITING_DATA
    if any(CHECKOUT_PRESENTED_RE.search(t) for t in ours):
        return HOT

    if not any(prices_in(t) for t in ours):
        return INTERESTED

    # Расчёт клиент видел. Ступень выше — только если он на него ОТВЕТИЛ чем-то
    # по делу: город, цвет, размер. Молчание после цены — это «Есть расчет»,
    # именно такие диалоги и уходят в пинги.
    slots = collect_slots([
        ("client" if m.role == MessageRole.client else "manager", m.text)
        for m in messages
    ])
    if any(slots.get(slot) for slot in _CLARIFYING_SLOTS):
        return CLARIFYING
    return CALCULATED


async def sync_status(
    db: AsyncSession, dialog: Dialog, *, ctx: str = "", now=None,
) -> str | None:
    """Поднять диалог на заслуженную ступень. Возвращает новое имя или None.

    Три правила, без которых лестница вредна:

    * только вперёд — ступень ниже текущей не ставится никогда, иначе диалог
      поедет назад, как «Горячий» → «Есть расчет» → «Горячий» в диалоге 142;
    * боковой статус неприкосновенен — диалог, переданный человеку или
      отписавшийся от сообщества, лестница не трогает;
    * статуса нет в базе или он выключен в админке — молча ничего не делаем:
      имена статусов заводятся руками, и падать из-за этого ход не должен.
    """
    current = None
    if dialog.current_status_id:
        current_obj = await db.get(DialogStatusConfig, dialog.current_status_id)
        current = current_obj.name if current_obj else None

    if current in SIDE_STATUSES:
        return None
    # Статус, которого нет в лестнице и который не боковой, — ручная пометка
    # менеджера или выключенный статус из админки. Такой не двигаем.
    if current is not None and not is_ladder(current):
        return None

    target = await earned_status(db, dialog)
    if rank(target) <= rank(current):
        return None

    row = await db.scalar(
        select(DialogStatusConfig).where(
            DialogStatusConfig.name == target,
            DialogStatusConfig.is_active == True,
        )
    )
    if row is None:
        logger.warning(
            "[%s] статус %r не заведён в базе — ступень не поставлена | dialog=%s",
            ctx, target, dialog.id,
        )
        return None

    dialog.current_status_id = row.id
    logger.info("[%s] статус по фактам | %s -> %s | dialog=%s", ctx, current, target, dialog.id)

    await _apply_side_effects(db, dialog, target, now)
    return target


async def _apply_side_effects(db: AsyncSession, dialog: Dialog, target: str, now) -> None:
    """Пинги, привязанные к ступени: раньше это висело в runner и работало
    только на том пути, где статус ставила модель."""
    from app.db.models import DialogPingState

    if dialog.ai_paused and target == AWAITING_PREPAY:
        # Счёт выставил менеджер, забравший диалог, — и лестница вызвана как раз
        # из его ответа (вебхук ВК, панель, наблюдатель MAX), где пинги только
        # что погашены. Заводить воронку заново значит писать поверх живого
        # разговора: «пинги должны отключаться, когда диалог переведён на
        # менеджера».
        logger.info("ping: воронка не заводится — диалог ведёт человек | dialog=%s", dialog.id)
        return

    if target == AWAITING_PREPAY:
        # Клиент получил счёт — общая воронка «знает цену» ему больше не
        # подходит: дожимать предоплату надо своей лестницей пингов.
        from app.ping.worker import force_ping_funnel
        from app.utils.time import msk_now

        await force_ping_funnel(db, dialog, "after_payment", now or msk_now())
    elif target == ORDER_CREATED:
        state = await db.scalar(
            select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
        )
        if state and not state.is_completed:
            state.is_completed = True
            logger.info("ping: остановлены — заказ оформлен | dialog=%s", dialog.id)
