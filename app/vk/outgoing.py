"""Учёт того, что мы реально отправили клиенту.

Две задачи, у которых один источник данных — метаданные исходящего сообщения.

1. Доставка. Строка Message создаётся и коммитится в run_ai ДО отправки в ВК, а
   отправка идёт позже. Упала отправка — строка остаётся, и модель на следующем
   ходу читает её как уже сказанное и шаг воронки не повторяет. У 85 из 314
   наших исходящих `external_message_id` пуст: они есть в истории и их нет у
   клиента.

2. Своё эхо. ВК присылает нам message_reply и о собственных отправках тоже.
   Раньше их отсекали по `random_id != 0` — в расчёте на то, что random_id
   бывает только у нас. На деле его проставляет любой отправитель: и клиент ВК,
   из которого пишет живой менеджер, и вторая система на группе. В выгрузке из
   ВК random_id ≠ 0 стоит у ВСЕХ исходящих, поэтому под фильтр попадали 100 %
   чужих сообщений, и за всю историю в базе не появилось ни одного сообщения с
   ролью curator. Отсюда же и то, что ИИ перебивал менеджера, а пинги не
   выключались.

   Теперь своё узнаём по факту: сохраняем random_id, которыми отправляли, и
   сверяем входящее эхо с ними.
"""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageRole
from app.utils.time import msk_now

logger = logging.getLogger(__name__)

# Ключ метаданных: сообщение дошло до ВК.
DELIVERED = "delivered"
# Ключ метаданных: отправка провалилась, клиент этого текста не видел.
DELIVERY_FAILED = "delivery_failed"
# Ключ метаданных: random_id всех частей, которыми ушёл этот текст.
RANDOM_IDS = "vk_random_ids"

# Насколько назад ищем свой random_id. Эхо приходит секундами позже отправки;
# час — запас на ретраи ВК, при этом выборка остаётся короткой.
_ECHO_LOOKBACK = timedelta(hours=1)
# Сколько последних исходящих просматриваем. Ход даёт максимум пять сообщений,
# тридцати хватает с большим запасом.
_ECHO_LIMIT = 30


def _patch(message: Message, **fields) -> None:
    """Дописать ключи в msg_metadata.

    Словарь пересобираем целиком: SQLAlchemy не отслеживает мутацию вложенного
    словаря в JSON-колонке и молча не сохранит изменение.
    """
    message.msg_metadata = {**(message.msg_metadata or {}), **fields}


def mark_delivered(message: Message, sent) -> None:
    """Отметить сообщение доставленным и запомнить его VK id и random_id."""
    fields = {DELIVERED: True, DELIVERY_FAILED: None}
    if getattr(sent, "random_ids", None):
        fields[RANDOM_IDS] = list(sent.random_ids)
    _patch(message, **fields)
    vk_id = getattr(sent, "message_id", None)
    if vk_id and not message.external_message_id:
        message.external_message_id = str(vk_id)


def mark_failed(message: Message) -> None:
    """Отметить, что текст до клиента не дошёл: в историю для модели он не идёт."""
    _patch(message, **{DELIVERED: False, DELIVERY_FAILED: True})


def was_delivered(message: Message) -> bool:
    """Дошло ли сообщение до клиента.

    Сообщения, отправленные до появления этих отметок, считаем доставленными:
    иначе вся прошлая история разом выпала бы из контекста модели.
    """
    return not (message.msg_metadata or {}).get(DELIVERY_FAILED)


def delivered_only(messages: list[Message]) -> list[Message]:
    """Отсеять то, что записано в базу, но клиенту не ушло."""
    return [m for m in messages if was_delivered(m)]


async def is_our_echo(
    db: AsyncSession, dialog_id: int, random_id: int, external_message_id: str | None,
) -> bool:
    """Это ВК вернул нам наше же исходящее, а не сообщение живого человека?

    Сначала по VK id (он проставляется на исходящих), затем по random_id: у
    пингов VK id раньше не сохранялся вовсе, и на старых записях остаётся только
    этот путь.
    """
    # Сначала — память процесса: там random_id оказывается ДО обращения к ВК,
    # тогда как в базе он появится только после коммита всего хода. Именно на
    # этом промежутке мы и принимали собственное эхо за живого оператора.
    from app.vk.sender import is_own_random_id

    if is_own_random_id(random_id):
        return True

    if external_message_id:
        seen = await db.scalar(
            select(Message.id).where(
                Message.dialog_id == dialog_id,
                Message.external_message_id == external_message_id,
                Message.role != MessageRole.client,
            )
        )
        if seen is not None:
            return True

    if not random_id:
        # random_id = 0 бывает у входящих; в исходящем это значит, что отправляли
        # не мы — свой мы всегда проставляем ненулевым (см. make_random_id).
        return False

    rows = await db.execute(
        select(Message.msg_metadata)
        .where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
            Message.created_at >= msk_now() - _ECHO_LOOKBACK,
        )
        .order_by(Message.id.desc())
        .limit(_ECHO_LIMIT)
    )
    for (meta,) in rows.all():
        if random_id in ((meta or {}).get(RANDOM_IDS) or []):
            return True
    return False
