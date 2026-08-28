"""Shared guards for outbound messages that may start automated follow-ups."""

from app.db.models import Message, MessageRole


def is_non_broadcast_curator_message(message: Message) -> bool:
    """A real manager reply, as opposed to a bulk mailing stored as curator."""
    metadata = message.msg_metadata or {}
    return (
        message.role == MessageRole.curator
        and not metadata.get("broadcast", False)
        and not metadata.get("delivery_failed", False)
    )


def is_pingable_outbound(message: Message) -> bool:
    """Last outbound message may be followed up when the dialog is unpaused.

    A manager reply normally pauses AI. If the dialog is unpaused afterwards,
    that is an explicit hand-back to automation and the reply should no longer
    block pings forever. Broadcasts are curator messages too, but are never a
    hand-back point and must not start an individual follow-up sequence.
    """
    return message.role == MessageRole.ai or is_non_broadcast_curator_message(message)
