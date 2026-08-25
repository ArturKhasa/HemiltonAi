"""CRUD /api/max-bots: подключение бота токеном и галочкой, подписка на вебхук."""
import pytest
from sqlalchemy import select

from app.auth.service import hash_password
from app.db.models import Client, User, UserRole, VkGroup


@pytest.fixture(autouse=True)
def panel_url(monkeypatch):
    """Адрес вебхука собирается из PANEL_PUBLIC_URL — без него MAX некуда писать."""
    monkeypatch.setattr("app.config.settings.PANEL_PUBLIC_URL", "https://ai.example.ru")


@pytest.fixture
def max_api(monkeypatch):
    """Подменяем MAX: тесты не ходят в сеть, но видят, что мы туда звали."""
    calls = {"subscribe": [], "unsubscribe": [], "me": 0}

    async def _get_me(token):
        calls["me"] += 1
        return {"user_id": 777001, "first_name": "Хэмилтон", "username": "hemilton_bot"}

    async def _subscribe(token, url, secret):
        calls["subscribe"].append((token, url, secret))
        return {"success": True}

    async def _unsubscribe(token, url):
        calls["unsubscribe"].append((token, url))
        return {"success": True}

    async def _list_subscriptions(token):
        return [{"url": u} for _, u, _ in calls["subscribe"]]

    monkeypatch.setattr("app.api.max_bots.max_api.get_me", _get_me)
    monkeypatch.setattr("app.api.max_bots.max_api.subscribe", _subscribe)
    monkeypatch.setattr("app.api.max_bots.max_api.unsubscribe", _unsubscribe)
    monkeypatch.setattr("app.api.max_bots.max_api.list_subscriptions", _list_subscriptions)
    return calls


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


async def test_token_plus_checkbox_connects_bot(client, db, admin_headers, max_api):
    """Ровно то, что делает админ: вставил токен, оставил галочку — бот работает."""
    resp = await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Хэмилтон", "access_token": "max-secret-token-abcd", "is_active": True,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["bot_id"] == 777001
    assert data["username"] == "hemilton_bot"
    assert data["is_active"] is True
    assert data["webhook_subscribed"] is True
    # Токен наружу не отдаём — только маска.
    assert "access_token" not in data
    assert data["access_token_mask"] == "…abcd"

    bot = await db.scalar(select(VkGroup).where(VkGroup.platform == "max"))
    assert bot.access_token == "max-secret-token-abcd"
    # Подписку ставим сами: в кабинет MAX админу ходить не нужно.
    assert max_api["subscribe"] == [
        ("max-secret-token-abcd", f"https://ai.example.ru/webhook/max/{bot.id}", bot.secret_key)
    ]
    assert data["webhook_url"] == f"https://ai.example.ru/webhook/max/{bot.id}"


async def test_inactive_bot_is_not_subscribed(client, admin_headers, max_api):
    resp = await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Хэмилтон", "access_token": "tok", "is_active": False,
    })
    assert resp.status_code == 201
    assert resp.json()["webhook_subscribed"] is False
    assert max_api["subscribe"] == []


async def test_list_returns_bots_added_in_admin(client, admin_headers, max_api):
    """После перезагрузки админки её GET должен вернуть созданную строку."""
    created = await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Хэмилтон", "access_token": "tok", "is_active": False,
    })
    assert created.status_code == 201

    listed = await client.get("/api/max-bots/", headers=admin_headers)
    assert listed.status_code == 200
    assert [bot["id"] for bot in listed.json()] == [created.json()["id"]]
    assert listed.json()[0]["name"] == "Хэмилтон"


async def test_toggle_active_subscribes_and_unsubscribes(client, admin_headers, max_api):
    created = (await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Хэмилтон", "access_token": "tok", "is_active": False,
    })).json()

    on = await client.patch(
        f"/api/max-bots/{created['id']}", headers=admin_headers, json={"is_active": True},
    )
    assert on.json()["webhook_subscribed"] is True
    assert len(max_api["subscribe"]) == 1

    off = await client.patch(
        f"/api/max-bots/{created['id']}", headers=admin_headers, json={"is_active": False},
    )
    assert off.json()["is_active"] is False
    assert off.json()["webhook_subscribed"] is False
    assert len(max_api["unsubscribe"]) == 1


async def test_bad_token_is_rejected_with_reason(client, admin_headers, monkeypatch):
    from app.max.client import MaxApiError

    async def _bad(token):
        raise MaxApiError(401, "auth.error", "Invalid access token")

    monkeypatch.setattr("app.api.max_bots.max_api.get_me", _bad)
    resp = await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Бот", "access_token": "wrong", "is_active": True,
    })
    assert resp.status_code == 400
    assert "Invalid access token" in resp.json()["detail"]


async def test_duplicate_bot_conflict(client, admin_headers, max_api):
    payload = {"name": "Бот", "access_token": "tok", "is_active": False}
    assert (await client.post("/api/max-bots/", headers=admin_headers, json=payload)).status_code == 201
    assert (await client.post("/api/max-bots/", headers=admin_headers, json=payload)).status_code == 409


async def test_patch_empty_token_keeps_current(client, db, admin_headers, max_api):
    created = (await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Бот", "access_token": "original-token", "is_active": False,
    })).json()
    resp = await client.patch(
        f"/api/max-bots/{created['id']}", headers=admin_headers,
        json={"name": "Переименован", "access_token": ""},
    )
    assert resp.status_code == 200
    bot = await db.get(VkGroup, created["id"])
    await db.refresh(bot)
    assert bot.access_token == "original-token"
    assert bot.name == "Переименован"


async def test_check_reports_missing_subscription(client, db, admin_headers, max_api, monkeypatch):
    """Подписку могли снять с той стороны — кнопка «Проверить» это показывает."""
    created = (await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Бот", "access_token": "tok", "is_active": True,
    })).json()
    assert created["webhook_subscribed"] is True

    async def _empty(token):
        return []

    monkeypatch.setattr("app.api.max_bots.max_api.list_subscriptions", _empty)
    resp = await client.post(f"/api/max-bots/{created['id']}/check", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["webhook_subscribed"] is False


async def test_delete_refuses_when_clients_exist(client, db, admin_headers, max_api):
    created = (await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Бот", "access_token": "tok", "is_active": False,
    })).json()
    db.add(Client(vk_user_id=555, vk_group_id=created["id"]))
    await db.commit()

    resp = await client.delete(f"/api/max-bots/{created['id']}", headers=admin_headers)
    assert resp.status_code == 409
    assert "выключите" in resp.json()["detail"].lower() or "снимите" in resp.json()["detail"].lower()


async def test_curator_has_no_access(client, curator_headers):
    assert (await client.get("/api/max-bots/", headers=curator_headers)).status_code == 403


async def test_max_bot_does_not_show_in_vk_groups(client, admin_headers, max_api):
    await client.post("/api/max-bots/", headers=admin_headers, json={
        "name": "Бот", "access_token": "tok", "is_active": False,
    })
    resp = await client.get("/api/vk-groups/", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == []
