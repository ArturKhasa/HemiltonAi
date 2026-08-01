"""Один прогон на диалог, ответ — на последнюю реплику.

Диалог 74: клиент отправил «я буду жаловаться!» в 04:06 и ещё раз в 04:07, а
прогон занимает десятки секунд. Второе сообщение стартовало собственный прогон,
пока первый ещё считал: два ответа подряд, и ни один не видел другого.
"""
import asyncio

import pytest

from app.ai.dialog_lock import (
    _PRUNE_THRESHOLD,
    _locks,
    dialog_lock,
    superseded_by_newer_message,
)
from app.db.models import Client, Dialog, DialogType, Message, MessageRole


@pytest.fixture
async def dialog(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    client = Client(vk_user_id=45345, name="Иван")
    db.add(client)
    await db.flush()
    d = Dialog(client_id=client.id, type_id=1)
    db.add(d)
    await db.commit()
    return d


class TestSuperseded:
    async def test_last_message_answers(self, db, dialog):
        first = Message(dialog_id=dialog.id, role=MessageRole.client, text="я буду жаловаться!")
        db.add(first)
        await db.commit()
        assert not await superseded_by_newer_message(db, dialog.id, first.id)

    async def test_earlier_message_yields(self, db, dialog):
        first = Message(dialog_id=dialog.id, role=MessageRole.client, text="я буду жаловаться!")
        db.add(first)
        await db.flush()
        second = Message(dialog_id=dialog.id, role=MessageRole.client, text="я буду жаловаться!")
        db.add(second)
        await db.commit()
        assert await superseded_by_newer_message(db, dialog.id, first.id)
        assert not await superseded_by_newer_message(db, dialog.id, second.id)

    async def test_our_own_reply_does_not_supersede(self, db, dialog):
        """Уступаем только реплике клиента — свой же ответ ход не отменяет."""
        client_msg = Message(dialog_id=dialog.id, role=MessageRole.client, text="привет")
        db.add(client_msg)
        await db.flush()
        db.add(Message(dialog_id=dialog.id, role=MessageRole.ai, text="Здравствуйте!"))
        await db.commit()
        assert not await superseded_by_newer_message(db, dialog.id, client_msg.id)

    async def test_other_dialog_does_not_supersede(self, db, dialog):
        msg = Message(dialog_id=dialog.id, role=MessageRole.client, text="привет")
        db.add(msg)
        await db.flush()
        # Диалог уникален парой (клиент, направление) — нужен второй клиент.
        other_client = Client(vk_user_id=45346, name="Пётр")
        db.add(other_client)
        await db.flush()
        other = Dialog(client_id=other_client.id, type_id=1)
        db.add(other)
        await db.flush()
        db.add(Message(dialog_id=other.id, role=MessageRole.client, text="и тут тоже"))
        await db.commit()
        assert not await superseded_by_newer_message(db, dialog.id, msg.id)


class TestDialogLock:
    def test_same_dialog_same_lock(self):
        assert dialog_lock(4242) is dialog_lock(4242)

    def test_different_dialogs_do_not_block_each_other(self):
        assert dialog_lock(4242) is not dialog_lock(4243)

    async def test_second_turn_waits_for_the_first(self):
        order: list[str] = []

        async def turn(name: str, delay: float) -> None:
            async with dialog_lock(777):
                order.append(f"{name}:начал")
                await asyncio.sleep(delay)
                order.append(f"{name}:закончил")

        await asyncio.gather(turn("первый", 0.05), turn("второй", 0))
        # Без блокировки было бы «первый:начал, второй:начал, ...» — прогоны внахлёст.
        assert order == [
            "первый:начал", "первый:закончил", "второй:начал", "второй:закончил",
        ]

    def test_free_locks_pruned_when_registry_grows(self):
        _locks.clear()
        held = dialog_lock(1)
        for i in range(2, _PRUNE_THRESHOLD + 2):
            dialog_lock(i)
        assert len(_locks) <= _PRUNE_THRESHOLD
        # Занятую блокировку не выбрасываем — иначе два прогона получат разные.
        _locks.clear()
        _locks[1] = held
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(held.acquire())
            for i in range(2, _PRUNE_THRESHOLD + 2):
                dialog_lock(i)
            assert dialog_lock(1) is held
        finally:
            loop.close()
            _locks.clear()
