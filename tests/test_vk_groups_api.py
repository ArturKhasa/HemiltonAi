"""CRUD /api/vk-groups: добавление группы из админки, маска токена, роли."""
import pytest
from sqlalchemy import select

from app.auth.service import hash_password
from app.db.models import User, UserRole, VkGroup


async def _auth_headers(client, db, email, role):
    db.add(User(email=email, password_hash=hash_password("pass1234"), role=role))
    await db.commit()
    resp = await client.post("/api/auth/login", json={"email": email, "password": "pass1234"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def admin_headers(client, db):
    return await _auth_headers(client, db, "boss@test.io", UserRole.admin)


@pytest.fixture
async def curator_headers(client, db):
    return await _auth_headers(client, db, "cur@test.io", UserRole.curator)


async def test_admin_can_add_vk_group(client, db, admin_headers):
    resp = await client.post("/api/vk-groups/", headers=admin_headers, json={
        "group_id": 222333,
        "name": "Магазин одежды",
        "access_token": "vk1.a.secret-token-abcd",
        "confirmation_code": "conf42",
        "secret_key": "shh",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["group_id"] == 222333
    # Токен наружу не отдаётся — только маска по последним символам.
    assert "access_token" not in data
    assert data["access_token_mask"] == "…abcd"
    assert data["has_secret"] is True

    group = await db.scalar(select(VkGroup).where(VkGroup.group_id == 222333))
    assert group.access_token == "vk1.a.secret-token-abcd"


async def test_duplicate_group_id_conflict(client, admin_headers):
    payload = {
        "group_id": 1, "name": "g", "access_token": "t", "confirmation_code": "c",
    }
    assert (await client.post("/api/vk-groups/", headers=admin_headers, json=payload)).status_code == 201
    assert (await client.post("/api/vk-groups/", headers=admin_headers, json=payload)).status_code == 409


async def test_patch_empty_token_keeps_current(client, db, admin_headers):
    created = (await client.post("/api/vk-groups/", headers=admin_headers, json={
        "group_id": 5, "name": "g", "access_token": "original-token", "confirmation_code": "c",
    })).json()
    resp = await client.patch(
        f"/api/vk-groups/{created['id']}", headers=admin_headers,
        json={"name": "renamed", "access_token": ""},
    )
    assert resp.status_code == 200
    group = await db.scalar(select(VkGroup).where(VkGroup.id == created["id"]))
    assert group.name == "renamed"
    assert group.access_token == "original-token"  # пустой токен = не менять


async def test_toggle_and_delete(client, admin_headers):
    created = (await client.post("/api/vk-groups/", headers=admin_headers, json={
        "group_id": 7, "name": "g", "access_token": "t", "confirmation_code": "c",
    })).json()
    resp = await client.patch(
        f"/api/vk-groups/{created['id']}", headers=admin_headers, json={"is_active": False},
    )
    assert resp.json()["is_active"] is False
    assert (await client.delete(f"/api/vk-groups/{created['id']}", headers=admin_headers)).status_code == 204
    listed = (await client.get("/api/vk-groups/", headers=admin_headers)).json()
    assert listed == []


async def test_curator_forbidden(client, curator_headers):
    resp = await client.get("/api/vk-groups/", headers=curator_headers)
    assert resp.status_code == 403
    resp = await client.post("/api/vk-groups/", headers=curator_headers, json={
        "group_id": 9, "name": "g", "access_token": "t", "confirmation_code": "c",
    })
    assert resp.status_code == 403


async def test_group_with_clients_is_not_deleted(client, db, admin_headers):
    """Клиенты ссылаются на группу внешним ключом: удаление роняло запрос
    пятисоткой (группа 1 с 58 клиентами на проде). Теперь — понятный отказ."""
    from app.db.models import Client as ClientModel

    resp = await client.post("/api/vk-groups/", headers=admin_headers, json={
        "group_id": 4242, "name": "Сообщество", "access_token": "vk1.a.tok",
        "confirmation_code": "conf",
    })
    group_pk = resp.json()["id"]
    db.add(ClientModel(vk_user_id=555, vk_group_id=group_pk, source="vk:4242"))
    await db.commit()

    resp = await client.delete(f"/api/vk-groups/{group_pk}", headers=admin_headers)
    assert resp.status_code == 409
    assert "1 клиент" in resp.json()["detail"]

    # Группа на месте — историю не потеряли.
    listing = await client.get("/api/vk-groups/", headers=admin_headers)
    assert any(g["id"] == group_pk for g in listing.json())


async def test_group_without_clients_is_deleted(client, db, admin_headers):
    resp = await client.post("/api/vk-groups/", headers=admin_headers, json={
        "group_id": 4343, "name": "Пустая", "access_token": "vk1.a.tok",
        "confirmation_code": "conf",
    })
    group_pk = resp.json()["id"]
    assert (await client.delete(f"/api/vk-groups/{group_pk}", headers=admin_headers)).status_code == 204
    listing = await client.get("/api/vk-groups/", headers=admin_headers)
    assert all(g["id"] != group_pk for g in listing.json())
