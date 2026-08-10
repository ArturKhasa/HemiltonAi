"""Учёт доставки и распознавание своего эха.

Две связанные вещи, из-за которых ИИ вёл себя так, будто разговаривает один.

Доставка: строка сообщения пишется до отправки в ВК. Упала отправка — строка
остаётся, и модель читает её как уже сказанное. У 85 из 314 исходящих
`external_message_id` пуст: они есть в истории и их нет у клиента.

Эхо: чужие исходящие отсекались по `random_id != 0`. Его проставляет любой
отправитель, включая клиент ВК живого менеджера, поэтому за всю историю в базе
не появилось ни одного сообщения с ролью curator — и ИИ перебивал менеджера.
"""
import pytest

from app.db.models import Client, Dialog, DialogType, Message, MessageRole
from app.vk.outgoing import (
    delivered_only,
    is_our_echo,
    mark_delivered,
    mark_failed,
    was_delivered,
)
from app.vk.sender import SentMessage


@pytest.fixture
async def dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    client = Client(vk_user_id=555)
    db.add(client)
    await db.flush()
    d = Dialog(client_id=client.id, type_id=1)
    db.add(d)
    await db.commit()
    return d


def _msg(dialog, text="текст", role=MessageRole.ai) -> Message:
    return Message(dialog_id=dialog.id, role=role, text=text)


class TestDelivery:
    def test_delivered_message_keeps_vk_ids(self, dialog):
        m = _msg(dialog)
        mark_delivered(m, SentMessage(message_id=161450, random_ids=[7, 8]))

        assert m.external_message_id == "161450"
        assert m.msg_metadata["vk_random_ids"] == [7, 8]
        assert was_delivered(m)

    def test_failed_message_drops_out_of_history(self, dialog):
        m = _msg(dialog, "Ваш первый макет уже отправлен дизайнеру")
        mark_failed(m)

        assert not was_delivered(m)
        assert delivered_only([m]) == []

    def test_old_messages_count_as_delivered(self, dialog):
        """Отметок нет у всего, что отправлено до этой правки: иначе вся прошлая
        история разом выпала бы из контекста модели."""
        assert was_delivered(_msg(dialog))

    def test_test_dialog_message_is_delivered_without_vk(self, dialog):
        """В тестовом диалоге клиента в ВК нет, но сообщение считается дошедшим."""
        m = _msg(dialog)
        mark_delivered(m, None)

        assert was_delivered(m)
        assert m.external_message_id is None


class TestEcho:
    async def test_our_own_send_is_recognised_by_random_id(self, db, dialog):
        m = _msg(dialog)
        mark_delivered(m, SentMessage(message_id=500, random_ids=[123456]))
        db.add(m)
        await db.commit()

        assert await is_our_echo(db, dialog.id, 123456, None) is True

    async def test_our_own_send_is_recognised_by_vk_id(self, db, dialog):
        m = _msg(dialog)
        mark_delivered(m, SentMessage(message_id=500, random_ids=[]))
        db.add(m)
        await db.commit()

        assert await is_our_echo(db, dialog.id, 999, "500") is True

    async def test_someone_elses_message_is_not_our_echo(self, db, dialog):
        """Ключевой случай: у живого менеджера random_id тоже ненулевой, но не наш."""
        m = _msg(dialog)
        mark_delivered(m, SentMessage(message_id=500, random_ids=[123456]))
        db.add(m)
        await db.commit()

        assert await is_our_echo(db, dialog.id, 1741129106, "161081") is False

    async def test_empty_dialog_has_no_echo(self, db, dialog):
        assert await is_our_echo(db, dialog.id, 42, "1") is False
