"""ИИ подхватывает только новые диалоги.

Требование заказчика от 20.08: «Есть диалоги, которые вели ранее, до сегодня. Но
лид ответил сегодня — тут запускается ИИ. Такое не должно быть». Сообщество
подключают к ИИ, когда у него уже годы переписок: лид, которого вели руками,
отвечает на рассылку, и ИИ начинал с «меня зовут София» поверх живой истории.
"""
import time

import pytest

from app.db.models import VkGroup
from app.vk.webhook import conversation_is_new

CLIENT = 555
GROUP = -238878717
NEW_MSG = "1000"


@pytest.fixture
def group():
    return VkGroup(id=2, group_id=238878717, name="Hemilton", access_token="t")


def _vk_returning(items, calls=None):
    async def _call(access_token, method, params):
        if calls is not None:
            calls.append((method, params))
        return {"count": len(items), "items": items}
    return _call


async def test_first_message_ever_is_a_new_conversation(group, monkeypatch):
    monkeypatch.setattr(
        "app.vk.sender.vk_api_call",
        _vk_returning([{"id": 1000, "from_id": CLIENT, "text": "Начать"}]),
    )
    assert await conversation_is_new(group, CLIENT, NEW_MSG) is True


async def test_community_greeting_before_it_still_counts_as_new(group, monkeypatch):
    """Сообщество пишет первым и новому лиду — кнопка «Начать» и рассылка."""
    monkeypatch.setattr(
        "app.vk.sender.vk_api_call",
        _vk_returning([
            {"id": 1000, "from_id": CLIENT, "text": "Начать", "date": int(time.time())},
            # Приветствие по кнопке «Начать» — за секунды до сообщения клиента.
            {"id": 999, "from_id": GROUP, "text": "Добро пожаловать!",
             "date": int(time.time()) - 5},
        ]),
    )
    assert await conversation_is_new(group, CLIENT, NEW_MSG) is True


async def test_broadcast_from_yesterday_is_an_old_conversation(group, monkeypatch):
    """«Не важно, рассылка была, лид сам написал по теме» — диалог всё равно
    вели до нас, ИИ в него не вступает."""
    monkeypatch.setattr(
        "app.vk.sender.vk_api_call",
        _vk_returning([
            {"id": 1000, "from_id": CLIENT, "text": "Давайте", "date": int(time.time())},
            {"id": 950, "from_id": GROUP, "text": "Ваш заказ ещё актуален?",
             "date": int(time.time()) - 86400},
        ]),
    )
    assert await conversation_is_new(group, CLIENT, NEW_MSG) is False


async def test_client_wrote_before_is_an_old_conversation(group, monkeypatch):
    monkeypatch.setattr(
        "app.vk.sender.vk_api_call",
        _vk_returning([
            {"id": 1000, "from_id": CLIENT, "text": "Да, актуально"},
            {"id": 900, "from_id": GROUP, "text": "Подскажите, заказ ещё актуален?"},
            {"id": 800, "from_id": CLIENT, "text": "Спасибо, подумаю"},
        ]),
    )
    assert await conversation_is_new(group, CLIENT, NEW_MSG) is False


async def test_vk_failure_keeps_the_ai_working(group, monkeypatch):
    """Молчание в диалоге нового лида дороже лишнего ответа в старом."""
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("VK unavailable")

    monkeypatch.setattr("app.vk.sender.vk_api_call", _boom)
    assert await conversation_is_new(group, CLIENT, NEW_MSG) is True


async def test_history_is_asked_for_this_client_only(group, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "app.vk.sender.vk_api_call",
        _vk_returning([{"id": 1000, "from_id": CLIENT}], calls),
    )
    await conversation_is_new(group, CLIENT, NEW_MSG)
    method, params = calls[0]
    assert method == "messages.getHistory"
    assert params["user_id"] == CLIENT
