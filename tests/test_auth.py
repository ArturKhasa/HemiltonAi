import pytest


async def test_register_creates_user(client):
    resp = await client.post("/api/auth/register", json={
        "email": "test@monroe.ru",
        "password": "secret123",
        "role": "curator",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@monroe.ru"
    assert data["role"] == "curator"
    assert "password_hash" not in data


async def test_login_returns_token(client):
    await client.post("/api/auth/register", json={
        "email": "login@monroe.ru",
        "password": "secret123",
        "role": "curator",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "login@monroe.ru",
        "password": "secret123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client):
    await client.post("/api/auth/register", json={
        "email": "bad@monroe.ru",
        "password": "secret123",
        "role": "curator",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "bad@monroe.ru",
        "password": "wrong",
    })
    assert resp.status_code == 401


async def test_me_requires_auth(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_returns_user(client):
    await client.post("/api/auth/register", json={
        "email": "me@monroe.ru",
        "password": "secret123",
        "role": "curator",
    })
    login = await client.post("/api/auth/login", json={
        "email": "me@monroe.ru",
        "password": "secret123",
    })
    token = login.json()["access_token"]
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@monroe.ru"
