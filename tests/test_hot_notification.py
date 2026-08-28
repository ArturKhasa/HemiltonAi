"""Уведомление в телеграм, когда лид становится «Горячим».

Артур на созвоне 27.08: «Кидать уведомление о статусе "Горячий клиент" — в чат
тг». Момент выбран не случайно: до этого шага диалог ведёт ИИ сам, а «Горячий» в
новом смысле означает, что клиенту показаны способы оплаты — дальше решается
оплата, и человек нужен рядом.

Уведомление уходит из лестницы статусов, то есть ровно один раз за диалог:
ступень ниже текущей не ставится, повторно «Горячий» не наступит.
"""
import pytest

from app.db.models import (
    Client, Dialog, DialogStatusConfig, Message, MessageRole, VkGroup,
)
from app.sales.status_flow import sync_status
from app.sales.status_names import CALCULATED, HOT, LADDER

PRICE = "Стоимость толстовки со скидкой СЕГОДНЯ - 5 990 ₽"
CHECKOUT = "Получается сумма заказа - 5 990 ₽\n\nА по оплате у нас есть 2 удобных варианта:"


@pytest.fixture
async def statuses(db):
    for order, name in enumerate(LADDER, start=1):
        db.add(DialogStatusConfig(name=name, pattern="", is_active=True, sort_order=order * 10))
    await db.commit()


@pytest.fixture
async def sent(monkeypatch):
    """Перехватываем отправку в телеграм — сети в наборе быть не должно."""
    calls = []

    async def _fake(text, what, dialog_id):
        calls.append({"text": text, "what": what, "dialog_id": dialog_id})

    monkeypatch.setattr("app.notify._send", _fake)
    monkeypatch.setattr("app.notify.notifications_configured", lambda: True)
    return calls


@pytest.fixture
async def dialog(db):
    group = VkGroup(platform="vk", group_id=44440184, name="Hemilton",
                    access_token="t", confirmation_code="c")
    db.add(group)
    await db.flush()
    c = Client(vk_user_id=189680451, name="Алексей", last_name="Смирнов",
               vk_group_id=group.id, marketing_tags=["pashapatriot1"])
    db.add(c)
    await db.flush()
    d = Dialog(client_id=c.id, type_id=None, is_test=False)
    db.add(d)
    await db.flush()
    await db.commit()
    return d


async def _say(db, dialog, role, text):
    db.add(Message(dialog_id=dialog.id, role=role, text=text))
    await db.commit()


class TestHotNotification:
    async def test_fires_when_payment_options_are_sent(self, db, dialog, statuses, sent):
        await _say(db, dialog, MessageRole.ai, CHECKOUT)
        assert await sync_status(db, dialog) == HOT
        assert len(sent) == 1
        text = sent[0]["text"]
        assert "Горячий лид" in text and "Алексей Смирнов" in text
        assert "vk.com/id189680451" in text
        assert "pashapatriot1" in text

    async def test_silent_on_the_earlier_rungs(self, db, dialog, statuses, sent):
        """Расчёт отправлен — это ещё не повод дёргать людей."""
        await _say(db, dialog, MessageRole.ai, PRICE)
        assert await sync_status(db, dialog) == CALCULATED
        assert sent == []

    async def test_fires_once_per_dialog(self, db, dialog, statuses, sent):
        await _say(db, dialog, MessageRole.ai, CHECKOUT)
        assert await sync_status(db, dialog) == HOT
        # Второй прогон по тому же диалогу ступень не меняет — и не звонит.
        assert await sync_status(db, dialog) is None
        assert len(sent) == 1

    async def test_max_client_gets_no_vk_link(self, db, dialog, statuses, sent):
        """Ссылка vk.com/id… для клиента из MAX вела бы на чужой профиль."""
        group = await db.get(VkGroup, 1)
        group.platform = "max"
        await db.commit()
        await _say(db, dialog, MessageRole.ai, CHECKOUT)
        await sync_status(db, dialog)
        assert "MAX id189680451" in sent[0]["text"]
        assert "vk.com/id" not in sent[0]["text"]


class TestNotConfigured:
    async def test_nothing_sent_without_a_token(self, db, dialog, statuses, monkeypatch):
        """Бот не заведён — ход клиента от этого падать не должен."""
        calls = []

        async def _fake(text, what, dialog_id):
            calls.append(text)

        monkeypatch.setattr("app.notify._send", _fake)
        monkeypatch.setattr("app.notify.notifications_configured", lambda: False)
        await _say(db, dialog, MessageRole.ai, CHECKOUT)
        assert await sync_status(db, dialog) == HOT
        assert calls == []
