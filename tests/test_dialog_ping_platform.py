"""Тег «Идёт пинг» и платформа в списке диалогов.

ОП, 27 августа: «было бы круто добавить тег ИДЕТ ПИНГ <…> сразу видим диалоги,
которые пингуются и нам не нужно тратить время, чтобы проваливаться в сам
диалог» и «было бы хорошо различать платформу макс/вк».

Метка обязана быть честной: воронка, once completed, заново не заводится
(discover() пропускает диалоги, у которых запись уже есть), а паузу ИИ и
блокировку отправки воркер увидит только на ближайшем проходе — до него
`is_completed` ещё false. Поэтому оба случая снимаются сразу.
"""
import csv
import io

import pytest

from app.auth.service import hash_password
from app.db.models import (
    Client, Dialog, DialogPingState, DialogType, User, UserRole, VkGroup,
)


@pytest.fixture
async def headers(client, db):
    db.add(User(email="boss@test.io", password_hash=hash_password("pass1234"), role=UserRole.admin))
    await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": "boss@test.io", "password": "pass1234"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def leads(db):
    """Шесть диалогов на все интересные сочетания.

    vk_id 1 — пингуется в ВК; 2 — пингуется в MAX; 3 — воронка закрыта;
    4 — воронки не было; 5 — воронка жива, но диалог забрал оператор;
    6 — воронка жива, но клиент запретил сообщения.
    """
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add(VkGroup(
        id=1, platform="vk", group_id=44440184, name="Hemilton MAIN",
        access_token="t", dialog_type_id=1,
    ))
    db.add(VkGroup(
        id=2, platform="max", group_id=165716466071, name="MAX-бот",
        access_token="t", dialog_type_id=1,
    ))
    await db.flush()

    # (vk_id, канал, воронка: None | «жива» | «закрыта», пауза, блок)
    rows = [
        (1, 1, "жива", False, False),
        (2, 2, "жива", False, False),
        (3, 1, "закрыта", False, False),
        (4, 1, None, False, False),
        (5, 1, "жива", True, False),
        (6, 1, "жива", False, True),
    ]
    for vk_id, group_id, funnel, paused, blocked in rows:
        c = Client(vk_user_id=vk_id, name=f"Клиент {vk_id}", vk_group_id=group_id)
        db.add(c)
        await db.flush()
        d = Dialog(
            client_id=c.id, type_id=1, is_test=False,
            ai_paused=paused, vk_blocked=blocked,
        )
        db.add(d)
        await db.flush()
        if funnel is not None:
            db.add(DialogPingState(
                dialog_id=d.id, funnel_type="knows_price", current_step=2,
                is_completed=(funnel == "закрыта"),
            ))
    await db.commit()


async def _rows(client, headers, params=None):
    resp = await client.get("/api/chat/dialogs", headers=headers, params=params or {})
    assert resp.status_code == 200
    return {d["vk_user_id"]: d for d in resp.json()}


class TestPingBadge:
    async def test_active_funnel_shows_the_badge(self, client, headers, leads):
        rows = await _rows(client, headers)
        assert rows[1]["ping_active"] is True
        assert rows[2]["ping_active"] is True

    async def test_completed_funnel_does_not(self, client, headers, leads):
        """Закрытую воронку заново не заводят — пингов больше не будет."""
        assert (await _rows(client, headers))[3]["ping_active"] is False

    async def test_no_funnel_at_all_does_not(self, client, headers, leads):
        assert (await _rows(client, headers))[4]["ping_active"] is False

    async def test_paused_dialog_does_not(self, client, headers, leads):
        """Диалог забрал оператор: воркер закроет воронку на ближайшем проходе,
        и обещать пинг нельзя уже сейчас."""
        assert (await _rows(client, headers))[5]["ping_active"] is False

    async def test_blocked_dialog_does_not(self, client, headers, leads):
        assert (await _rows(client, headers))[6]["ping_active"] is False


class TestPingFilter:
    async def test_filter_active(self, client, headers, leads):
        rows = await _rows(client, headers, {"ping_active": "true"})
        assert sorted(rows) == [1, 2]

    async def test_filter_inactive(self, client, headers, leads):
        rows = await _rows(client, headers, {"ping_active": "false"})
        assert sorted(rows) == [3, 4, 5, 6]

    async def test_count_matches_list(self, client, headers, leads):
        resp = await client.get(
            "/api/chat/dialogs/count", headers=headers, params={"ping_active": "true"},
        )
        assert resp.json()["count"] == 2


class TestPlatform:
    async def test_platform_is_in_the_list(self, client, headers, leads):
        rows = await _rows(client, headers)
        assert rows[1]["platform"] == "vk"
        assert rows[2]["platform"] == "max"

    async def test_filter_by_max(self, client, headers, leads):
        assert sorted(await _rows(client, headers, {"platform": "max"})) == [2]

    async def test_filter_by_vk(self, client, headers, leads):
        assert sorted(await _rows(client, headers, {"platform": "vk"})) == [1, 3, 4, 5, 6]

    async def test_dialog_without_a_channel_counts_as_vk(self, client, headers, db, leads):
        """Тестовый диалог из панели канала не имеет вовсе — как и везде в коде,
        считаем его ВК (см. messaging.platform_of)."""
        c = Client(vk_user_id=99, name="Тестовый")
        db.add(c)
        await db.flush()
        db.add(Dialog(client_id=c.id, type_id=1, is_test=False))
        await db.commit()
        rows = await _rows(client, headers)
        assert rows[99]["platform"] == "vk"
        assert 99 in await _rows(client, headers, {"platform": "vk"})


class TestExport:
    async def test_csv_has_both_columns(self, client, headers, leads):
        resp = await client.get("/api/chat/dialogs/export", headers=headers)
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert "platform" in rows[0] and "ping_active" in rows[0]
        by_id = {r["vk_user_id"]: r for r in rows}
        assert by_id["2"]["platform"] == "max"
        assert by_id["1"]["ping_active"] == "True"
        assert by_id["3"]["ping_active"] == "False"

    async def test_export_respects_the_ping_filter(self, client, headers, leads):
        resp = await client.get(
            "/api/chat/dialogs/export-ids", headers=headers, params={"ping_active": "true"},
        )
        assert resp.status_code == 200
        assert sorted(resp.text.split(";")) == ["1", "2"]
