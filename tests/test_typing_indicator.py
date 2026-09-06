"""«Печатает…», пока ИИ готовит ответ.

Лена, 04.09: «Пока ИИ думает 30 секунд, можно включить видимость, что
сообщество печатает в это время, чтобы лиды видели, что мы не просто игнорим,
а пишем что-то в этот момент?». С паузой в 30 секунд (PLAN-2026-09-04, пункт G)
ответ идёт полторы-две минуты, и немой чат лид читает как «меня игнорируют».

Мессенджеры гасят индикатор через несколько секунд, поэтому одной отправки
мало — фоновая задача повторяет его, пока идёт ожидание и прогон.
"""
import asyncio

import pytest

from app.db.models import Client, VkGroup
from app.max import client as max_client
from app.vk import sender, webhook


class TestVkSendTyping:
    async def test_calls_set_activity(self, monkeypatch):
        calls = []

        async def _fake(token, method, params):
            calls.append((token, method, params))

        monkeypatch.setattr(sender, "vk_api_call", _fake)

        await sender.send_typing("tok", 4242, group_id=777)

        assert calls == [("tok", "messages.setActivity",
                          {"user_id": 4242, "type": "typing", "group_id": 777})]

    async def test_vk_error_does_not_propagate(self, monkeypatch):
        """Индикатор — украшение: из-за него ответ клиенту падать не должен."""
        async def _boom(token, method, params):
            raise RuntimeError("VK прилёг")

        monkeypatch.setattr(sender, "vk_api_call", _boom)

        await sender.send_typing("tok", 4242, group_id=777)


class TestMaxSendTyping:
    async def test_calls_the_actions_endpoint(self, monkeypatch):
        calls = []

        async def _fake(token, method, path, **kwargs):
            calls.append((method, path, kwargs.get("json")))

        monkeypatch.setattr(max_client, "_request", _fake)

        await max_client.send_typing("tok", 555)

        assert calls == [("POST", "/chats/555/actions", {"action": "typing_on"})]

    async def test_max_error_does_not_propagate(self, monkeypatch):
        """Эндпоинт живьём не проверен — если MAX его не знает, это не повод
        ронять ответ клиенту (см. комментарий в app.max.client.send_typing)."""
        async def _boom(token, method, path, **kwargs):
            raise RuntimeError("404")

        monkeypatch.setattr(max_client, "_request", _boom)

        await max_client.send_typing("tok", 555)


class TestTypingIndicator:
    """Обвязку тестируем на подменённой отправке: autouse-фикстура в conftest
    гасит её для всего набора, здесь ставим свой счётчик."""

    @pytest.fixture
    def sent(self, monkeypatch):
        calls = []

        async def _fake(platform, access_token, address, group_id):
            calls.append((platform, access_token, address, group_id))

        monkeypatch.setattr(webhook, "_send_typing_once", _fake)
        monkeypatch.setattr(webhook, "TYPING_REFRESH_SECONDS", 0.01)
        return calls

    def _vk(self):
        group = VkGroup(group_id=44440184, access_token="tok", platform="vk")
        return group, Client(vk_user_id=4242, name="Иван")

    async def test_starts_immediately(self, sent):
        group, client = self._vk()

        async with webhook.typing_indicator(group, client, "ctx"):
            # Даём фоновой задаче дойти до первой отправки.
            await asyncio.sleep(0.005)

        assert sent and sent[0] == ("vk", "tok", 4242, 44440184)

    async def test_repeats_while_the_answer_is_being_prepared(self, sent):
        group, client = self._vk()

        async with webhook.typing_indicator(group, client, "ctx"):
            await asyncio.sleep(0.05)

        # Индикатор гаснет за несколько секунд, поэтому одной отправки мало.
        assert len(sent) > 1

    async def test_stops_when_the_turn_is_over(self, sent):
        group, client = self._vk()

        async with webhook.typing_indicator(group, client, "ctx"):
            await asyncio.sleep(0.02)
        after_exit = len(sent)
        await asyncio.sleep(0.05)

        assert len(sent) == after_exit

    async def test_max_client_gets_its_chat_id(self, sent):
        group = VkGroup(group_id=342814196, access_token="tok", platform="max")
        client = Client(vk_user_id=139217864, name="Али", max_chat_id=987)

        async with webhook.typing_indicator(group, client, "ctx"):
            await asyncio.sleep(0.005)

        assert sent and sent[0] == ("max", "tok", 987, 342814196)

    async def test_max_without_chat_id_is_skipped(self, sent):
        """chat_id запоминается на первом сообщении диалога; пока его нет,
        адреса для индикатора просто не существует."""
        group = VkGroup(group_id=342814196, access_token="tok", platform="max")
        client = Client(vk_user_id=139217864, name="Али", max_chat_id=None)

        async with webhook.typing_indicator(group, client, "ctx"):
            await asyncio.sleep(0.02)

        assert sent == []

    async def test_channel_without_a_token_is_skipped(self, sent):
        group = VkGroup(group_id=44440184, access_token="", platform="vk")
        client = Client(vk_user_id=4242, name="Иван")

        async with webhook.typing_indicator(group, client, "ctx"):
            await asyncio.sleep(0.02)

        assert sent == []

    async def test_body_error_still_stops_the_indicator(self, sent):
        """Прогон упал — фоновая задача не должна пережить ход."""
        group, client = self._vk()

        with pytest.raises(RuntimeError):
            async with webhook.typing_indicator(group, client, "ctx"):
                await asyncio.sleep(0.02)
                raise RuntimeError("прогон упал")

        after_exit = len(sent)
        await asyncio.sleep(0.05)
        assert len(sent) == after_exit
