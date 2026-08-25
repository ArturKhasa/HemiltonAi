"""Выключенный канал не должен писать клиентам.

25.08 MAX-бота id165716466071_bot сняли с работы галочкой «Активен»: входящие он
принимать перестал, а пинги продолжали уходить — 20 воронок, семь сообщений за
полчаса. Для клиента это выглядело как «ИИ продолжает диалог», хотя его ответы
уже никуда не доходили. Гейт живёт в выборках пингов, а не в отправке: ручной
ответ менеджера из панели по выключенному каналу уйти по-прежнему должен.
"""
import inspect

from sqlalchemy import select

from app.db.models import Client, Dialog, VkGroup
from app.messaging import dialogs_on_inactive_channels


async def _dialog_on(db, *, is_active, vk_user_id) -> int:
    group = VkGroup(
        platform="max", group_id=vk_user_id, name="bot",
        access_token="t", is_active=is_active,
    )
    db.add(group)
    await db.flush()
    client = Client(vk_user_id=vk_user_id, vk_group_id=group.id, name="Оксана")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, type_id=1)
    db.add(dialog)
    await db.flush()
    return dialog.id


class TestInactiveChannelSubquery:
    async def test_dialog_of_disabled_bot_is_listed(self, db):
        dialog_id = await _dialog_on(db, is_active=False, vk_user_id=297394906)
        listed = (await db.execute(dialogs_on_inactive_channels())).scalars().all()
        assert listed == [dialog_id]

    async def test_dialog_of_working_bot_is_not_listed(self, db):
        await _dialog_on(db, is_active=True, vk_user_id=42)
        listed = (await db.execute(dialogs_on_inactive_channels())).scalars().all()
        assert listed == []

    async def test_test_dialog_without_channel_is_not_listed(self, db):
        """Тестовый диалог из панели канала не имеет — пинги по нему остаются."""
        client = Client(vk_user_id=None, vk_group_id=None, name="Тест")
        db.add(client)
        await db.flush()
        dialog = Dialog(client_id=client.id, type_id=1, is_test=True)
        db.add(dialog)
        await db.flush()

        listed = (await db.execute(dialogs_on_inactive_channels())).scalars().all()
        assert listed == []

    async def test_dialog_of_disabled_bot_is_filtered_out_of_a_query(self, db):
        """Так фильтр и стоит в выборках: NOT IN по id диалога."""
        dead = await _dialog_on(db, is_active=False, vk_user_id=297394906)
        alive = await _dialog_on(db, is_active=True, vk_user_id=42)

        rows = (await db.execute(
            select(Dialog.id).where(Dialog.id.not_in(dialogs_on_inactive_channels()))
        )).scalars().all()
        assert alive in rows and dead not in rows


class TestFilterIsWiredIntoTheSenders:
    def test_ping_discovery_skips_disabled_channels(self):
        from app.ping import worker
        assert "dialogs_on_inactive_channels()" in inspect.getsource(worker.discover)

    def test_due_pings_skip_disabled_channels(self):
        from app.ping import worker
        assert "dialogs_on_inactive_channels()" in inspect.getsource(worker.process_due)

    def test_price_to_silent_skips_disabled_channels(self):
        from app.ping import silent_greeting
        source = inspect.getsource(silent_greeting.send_price_to_silent)
        assert "dialogs_on_inactive_channels()" in source
