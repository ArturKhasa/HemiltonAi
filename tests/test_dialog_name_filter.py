"""Поиск диалога по имени клиента.

ОП, 24 августа: в списке 239 диалогов, и найти нужного человека глазами нельзя,
а числового VK ID менеджер не знает — он знает фамилию. Фильтр по ID для этого
не годится.

Имя и фамилия лежат в разных колонках, поэтому каждое слово запроса ищется в
обеих: «Аксёнов Денис» и «Денис Аксёнов» должны находить одного и того же
человека.
"""
import pytest

from app.auth.service import hash_password
from app.db.models import Client, Dialog, DialogType, User, UserRole


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
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    await db.flush()
    dialog_ids = []
    for vk_id, name, last_name in [
        (709008956, "Денис", "Аксёнов"),
        (465349448, "Илья", "Иноземцев"),
        (345905249, "Вячеслав", "Борисов"),
        (470376158, "Денис", "Борисов"),
        (866582523, None, None),
    ]:
        c = Client(vk_user_id=vk_id, name=name, last_name=last_name)
        db.add(c)
        await db.flush()
        dialog = Dialog(client_id=c.id, type_id=1, is_test=False)
        db.add(dialog)
        await db.flush()
        dialog_ids.append(dialog.id)
    await db.commit()
    return dialog_ids


async def _names(client, headers, query):
    resp = await client.get(
        "/api/chat/dialogs", headers=headers, params={"client_name": query},
    )
    assert resp.status_code == 200
    return sorted(
        f"{r['client_name']} {r['client_last_name']}" for r in resp.json()
    )


async def test_finds_by_surname(client, headers, leads):
    assert await _names(client, headers, "Аксёнов") == ["Денис Аксёнов"]


async def test_finds_by_first_name(client, headers, leads):
    assert await _names(client, headers, "Вячеслав") == ["Вячеслав Борисов"]


async def test_word_order_does_not_matter(client, headers, leads):
    assert await _names(client, headers, "Денис Аксёнов") == ["Денис Аксёнов"]
    assert await _names(client, headers, "Аксёнов Денис") == ["Денис Аксёнов"]


async def test_every_word_must_match(client, headers, leads):
    """«Денис Борисов» — это один конкретный человек, а не все Денисы и Борисовы."""
    assert await _names(client, headers, "Денис Борисов") == ["Денис Борисов"]


async def test_search_is_case_insensitive_and_partial(client, headers, leads):
    assert await _names(client, headers, "аксён") == ["Денис Аксёнов"]


async def test_unknown_name_finds_nothing(client, headers, leads):
    assert await _names(client, headers, "Иванов") == []


async def test_empty_filter_returns_everyone(client, headers, leads):
    resp = await client.get("/api/chat/dialogs", headers=headers)
    assert len(resp.json()) == 5


async def test_finds_exact_dialog_by_id_before_pagination(client, headers, leads):
    """Deep link получает нужную строку, даже если общий лимит равен единице."""
    target = leads[-1]
    resp = await client.get(
        "/api/chat/dialogs",
        headers=headers,
        params={"dialog_id": target, "limit": 1},
    )
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [target]


async def test_counter_matches_the_filtered_list(client, headers, leads):
    """Счётчик «Найдено: N» над списком считает то же самое."""
    resp = await client.get(
        "/api/chat/dialogs/count", headers=headers, params={"client_name": "Борисов"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


async def test_csv_export_respects_the_name_filter(client, headers, leads):
    resp = await client.get(
        "/api/chat/dialogs/export", headers=headers, params={"client_name": "Аксёнов"},
    )
    assert resp.status_code == 200
    assert "Аксёнов" in resp.text
    assert "Иноземцев" not in resp.text
