"""Feedback rules loader with in-memory TTL cache."""
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageFeedback

_rules_cache: dict[tuple, tuple[list[dict], float]] = {}
_RULES_TTL = 60


async def load_active_feedback_rules(
    db: AsyncSession,
    type_id: int | None,
    is_ping: bool = False,
) -> list[dict]:
    """Returns list of {message_text, rule_text} dicts."""
    cache_key = (type_id, is_ping)
    cached = _rules_cache.get(cache_key)
    if cached and time.time() - cached[1] < _RULES_TTL:
        return cached[0]

    result = await db.execute(
        select(MessageFeedback.rule_text, Message.text.label("message_text"))
        .join(Message, MessageFeedback.message_id == Message.id)
        .where(MessageFeedback.is_active == True)
        .where(MessageFeedback.type_id == type_id)
        .where(MessageFeedback.is_ping == is_ping)
        .order_by(MessageFeedback.created_at)
    )
    rules = [{"message_text": row.message_text, "rule_text": row.rule_text} for row in result.all()]
    _rules_cache[cache_key] = (rules, time.time())
    return rules


def invalidate_feedback_cache(type_id: int | None = None, is_ping: bool | None = None) -> None:
    if is_ping is None:
        for key in list(_rules_cache):
            if key[0] == type_id:
                _rules_cache.pop(key, None)
    else:
        _rules_cache.pop((type_id, is_ping), None)
