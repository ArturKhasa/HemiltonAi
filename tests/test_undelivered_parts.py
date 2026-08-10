"""Упавшая отправка не должна оставлять модели ложное «я это уже сказала».

Строка сообщения создаётся в run_ai и коммитится ДО отправки в ВК. Отправка
падает — строка остаётся, и на следующем ходу модель читает её как отправленное
и шаг воронки не повторяет. В проде так потерялись 85 исходящих из 314: у них
пуст external_message_id, в переписке ВК их нет (например «Ваш первый макет уже
отправлен дизайнеру» в диалоге 142, 14:32 — там были битые токены фото).
"""
import pytest
from sqlalchemy import select

from app.ai.runner import ReplyPart
from app.ai.schemas import AgentOutput
from app.db.models import Client, Dialog, DialogType, Message, MessageRole, VkGroup
from app.vk.outgoing import delivered_only, was_delivered
from app.vk.sender import SentMessage, VkApiError
from app.vk.webhook import handle_message_new, parse_message_event


@pytest.fixture
async def vk_group(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    g = VkGroup(group_id=111222, name="Магазин", access_token="tok", confirmation_code="c")
    db.add(g)
    await db.commit()
    return g


def _event(text="Привет", message_id=1):
    return {
        "type": "message_new",
        "group_id": 111222,
        "object": {"message": {
            "from_id": 555, "peer_id": 555, "text": text,
            "id": message_id, "random_id": 0,
        }},
    }


@pytest.fixture
def three_part_reply(monkeypatch):
    """run_ai отдаёт ход из трёх реплик — как связка «похвала → цена → доставка»."""
    async def _fake_run_ai(db, dialog, client_message):
        parts = []
        for text in ("Супер, зафиксировала", "Стоимость - 5 990 ₽", "В какой город доставка?"):
            m = Message(dialog_id=dialog.id, role=MessageRole.ai, text=text)
            db.add(m)
            await db.flush()
            parts.append(ReplyPart(text=text, image_urls=[], message=m))
        await db.commit()
        return AgentOutput(reply_text=parts[0].text, confidence_score=0.9), None, parts

    monkeypatch.setattr("app.ai.runner.run_ai", _fake_run_ai)


async def test_send_failure_marks_the_rest_undelivered(db, vk_group, three_part_reply, monkeypatch):
    """ВК принял первую реплику и упал на второй: третья до клиента тоже не дошла."""
    calls = []

    async def _send(db_, dialog, text):
        calls.append(text)
        if len(calls) == 1:
            return SentMessage(message_id=800, random_ids=[900])
        raise VkApiError(10, "Internal server error")

    monkeypatch.setattr("app.vk.sender.send_to_dialog", _send)

    await handle_message_new(db, vk_group, parse_message_event(_event()))

    rows = await db.execute(
        select(Message).where(Message.role == MessageRole.ai).order_by(Message.id)
    )
    msgs = list(rows.scalars().all())
    assert [was_delivered(m) for m in msgs] == [True, False, False]
    assert msgs[0].external_message_id == "800"
    # Именно это и уходит в контекст модели на следующем ходу.
    assert [m.text for m in delivered_only(msgs)] == ["Супер, зафиксировала"]


async def test_successful_send_records_vk_ids_on_every_part(db, vk_group, three_part_reply, monkeypatch):
    counter = {"n": 0}

    async def _send(db_, dialog, text):
        counter["n"] += 1
        return SentMessage(message_id=800 + counter["n"], random_ids=[900 + counter["n"]])

    monkeypatch.setattr("app.vk.sender.send_to_dialog", _send)
    monkeypatch.setattr("app.vk.webhook.FOLLOW_UP_DELAY_SECONDS", 0)

    await handle_message_new(db, vk_group, parse_message_event(_event()))

    rows = await db.execute(
        select(Message).where(Message.role == MessageRole.ai).order_by(Message.id)
    )
    msgs = list(rows.scalars().all())
    assert all(was_delivered(m) for m in msgs)
    # random_id нужны, чтобы не принять собственное эхо за сообщение менеджера.
    assert [m.msg_metadata["vk_random_ids"] for m in msgs] == [[901], [902], [903]]
