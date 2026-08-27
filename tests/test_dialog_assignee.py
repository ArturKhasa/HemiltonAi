"""Ответственный менеджер на диалоге.

Лена просила его дважды — 25.08 («Можем ли в панель пробрасывать ответственного
менеджера за клиентом из блюсейлс? Чтобы они сразу видели за кем следить») и
26.08. Интеграции с BlueSales не будет, поэтому ответственного назначают в
панели руками, из списка пользователей.

Смысл — в отборе: «у нас там выходит 500 клиентов, менеджеры же не будут каждого
своего по имени искать» (25.08, 11:32).
"""
import csv
import io

import pytest

from app.auth.service import hash_password
from app.db.models import (
    Client, Dialog, DialogType, User, UserDialogType, UserRole,
)
from app.utils.text import person_label


@pytest.fixture
async def team(db):
    db.add_all([
        DialogType(id=1, name="default", display_name="Основное"),
        DialogType(id=2, name="opt", display_name="Опт"),
    ])
    db.add_all([
        User(id=1, email="boss@test.io", password_hash=hash_password("pass1234"),
             role=UserRole.admin),
        # Имя заполнено — им и подписываем.
        User(id=2, email="hemilton1@mail.ru", password_hash=hash_password("x"),
             name="Лена", role=UserRole.curator),
        # Имени нет — подписываем частью адреса.
        User(id=3, email="hemilton2@mail.ru", password_hash=hash_password("x"),
             role=UserRole.curator),
        # Куратор чужого направления — в списке назначаемых не появляется.
        User(id=4, email="opt@mail.ru", password_hash=hash_password("x"),
             name="Оптовик", role=UserRole.curator),
    ])
    await db.flush()
    db.add_all([
        UserDialogType(user_id=2, type_id=1),
        UserDialogType(user_id=3, type_id=1),
        UserDialogType(user_id=4, type_id=2),
    ])
    await db.commit()


@pytest.fixture
async def headers(client, db, team):
    resp = await client.post(
        "/api/auth/login", json={"email": "boss@test.io", "password": "pass1234"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def leads(db, team):
    for vk_id, assignee in [(1, 2), (2, 2), (3, 3), (4, None)]:
        c = Client(vk_user_id=vk_id, name=f"Клиент {vk_id}")
        db.add(c)
        await db.flush()
        db.add(Dialog(
            client_id=c.id, type_id=1, is_test=False, assigned_curator_id=assignee,
        ))
    await db.commit()


async def _rows(client, headers, params=None):
    resp = await client.get("/api/chat/dialogs", headers=headers, params=params or {})
    assert resp.status_code == 200
    return {d["vk_user_id"]: d for d in resp.json()}


class TestLabel:
    def test_name_wins(self):
        assert person_label("Лена", "hemilton1@mail.ru") == "Лена"

    def test_falls_back_to_the_address(self):
        """«hemilton7» читается хуже живого имени, но лучше пустоты."""
        assert person_label(None, "hemilton7@mail.ru") == "hemilton7"
        assert person_label("   ", "hemilton7@mail.ru") == "hemilton7"

    def test_nothing_at_all(self):
        assert person_label(None, None) is None


class TestAssigneeList:
    async def test_lists_people_who_can_take_the_dialog(self, client, headers):
        resp = await client.get("/api/chat/assignees", headers=headers)
        assert resp.status_code == 200
        labels = {a["label"] for a in resp.json()}
        assert {"Лена", "hemilton2"} <= labels

    async def test_curator_sees_only_their_own_directions(self, client, db, team):
        """Назначать человека на диалог, которого он не увидит, смысла нет."""
        db.add(User(id=5, email="lena@test.io", password_hash=hash_password("pass1234"),
                    name="Лена-куратор", role=UserRole.curator))
        await db.flush()
        db.add(UserDialogType(user_id=5, type_id=1))
        await db.commit()
        resp = await client.post(
            "/api/auth/login", json={"email": "lena@test.io", "password": "pass1234"},
        )
        h = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        labels = {a["label"] for a in (await client.get("/api/chat/assignees", headers=h)).json()}
        assert "Оптовик" not in labels          # чужое направление
        assert "Лена" in labels                 # своё
        assert "boss" in labels                 # админ виден всегда


class TestAssign:
    async def test_assign_and_clear(self, client, headers, leads):
        dialog_id = (await _rows(client, headers))[4]["id"]

        resp = await client.post(
            f"/api/chat/dialogs/{dialog_id}/assignee", headers=headers, json={"user_id": 2},
        )
        assert resp.status_code == 200
        assert resp.json()["assignee_name"] == "Лена"
        assert (await _rows(client, headers))[4]["assignee_name"] == "Лена"

        resp = await client.post(
            f"/api/chat/dialogs/{dialog_id}/assignee", headers=headers, json={"user_id": None},
        )
        assert resp.status_code == 200
        assert (await _rows(client, headers))[4]["assignee_name"] is None

    async def test_unknown_user_is_rejected(self, client, headers, leads):
        dialog_id = (await _rows(client, headers))[4]["id"]
        resp = await client.post(
            f"/api/chat/dialogs/{dialog_id}/assignee", headers=headers, json={"user_id": 999},
        )
        assert resp.status_code == 400

    async def test_unknown_dialog(self, client, headers, team):
        resp = await client.post(
            "/api/chat/dialogs/424242/assignee", headers=headers, json={"user_id": 2},
        )
        assert resp.status_code == 404


class TestFilter:
    async def test_by_one_manager(self, client, headers, leads):
        assert sorted(await _rows(client, headers, {"assignee": "2"})) == [1, 2]

    async def test_by_several(self, client, headers, leads):
        got = await _rows(client, headers, [("assignee", "2"), ("assignee", "3")])
        assert sorted(got) == [1, 2, 3]

    async def test_without_a_manager(self, client, headers, leads):
        assert sorted(await _rows(client, headers, {"assignee": "__none__"})) == [4]

    async def test_count_matches_the_list(self, client, headers, leads):
        resp = await client.get(
            "/api/chat/dialogs/count", headers=headers, params={"assignee": "2"},
        )
        assert resp.json()["count"] == 2

    async def test_name_reaches_the_list(self, client, headers, leads):
        rows = await _rows(client, headers)
        assert rows[1]["assignee_name"] == "Лена"
        assert rows[3]["assignee_name"] == "hemilton2"
        assert rows[4]["assignee_name"] is None


class TestExport:
    async def test_csv_column(self, client, headers, leads):
        resp = await client.get("/api/chat/dialogs/export", headers=headers)
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        by_id = {r["vk_user_id"]: r for r in rows}
        assert by_id["1"]["assignee"] == "Лена"
        assert by_id["4"]["assignee"] == ""
