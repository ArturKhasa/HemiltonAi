"""Метка рекламной ссылки в списке диалогов: фильтр и список меток.

Георгий, 26 августа: «нужно добавить отображение тегов в списке диалогов и в
фильтры, чтобы менеджеры ориентировались». Метка приезжает из ref-ссылки
(app.vk.webhook) и лежит в clients.marketing_tags — фильтровать по ней надо на
сервере, а не по загруженной странице: диалогов сотни, а грузится по 50.

Клиент без метки — не ошибка: в группу приходят и из поиска, где ref нет вовсе.
Поэтому у фильтра есть отдельное значение «__none__».
"""
import pytest

from app.auth.service import hash_password
from app.db.models import Client, Dialog, DialogType, User, UserDialogType, UserRole


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
    db.add(DialogType(id=2, name="opt", display_name="Опт"))
    await db.flush()
    # (vk_id, метки, направление)
    for vk_id, tags, type_id in [
        (1, ["sweetgold"], 1),
        (2, ["sweetgold"], 1),
        (3, ["ПАВЕЛ_ПАТРИОТ_1"], 1),
        (4, None, 1),          # пришёл из поиска по группе — метки нет
        (5, [], 1),            # пустой массив: метки тоже нет
        (6, ["hood141"], 2),   # чужое направление
    ]:
        c = Client(vk_user_id=vk_id, name=f"Клиент {vk_id}", marketing_tags=tags)
        db.add(c)
        await db.flush()
        db.add(Dialog(client_id=c.id, type_id=type_id, is_test=False))
    await db.commit()


async def _ids(client, headers, params):
    resp = await client.get("/api/chat/dialogs", headers=headers, params=params)
    assert resp.status_code == 200
    return sorted(d["vk_user_id"] for d in resp.json())


async def test_filter_by_one_tag(client, headers, leads):
    assert await _ids(client, headers, {"marketing_tag": "sweetgold"}) == [1, 2]


async def test_filter_by_several_tags(client, headers, leads):
    """Несколько меток — объединение, как у чекбоксов статусов."""
    got = await _ids(client, headers, [
        ("marketing_tag", "sweetgold"), ("marketing_tag", "ПАВЕЛ_ПАТРИОТ_1"),
    ])
    assert got == [1, 2, 3]


async def test_filter_without_tag(client, headers, leads):
    """«Без метки» — и NULL, и пустой массив; помеченные не попадают."""
    assert await _ids(client, headers, {"marketing_tag": "__none__"}) == [4, 5]


async def test_filter_tag_with_none(client, headers, leads):
    got = await _ids(client, headers, [
        ("marketing_tag", "sweetgold"), ("marketing_tag", "__none__"),
    ])
    assert got == [1, 2, 4, 5]


async def test_no_filter_returns_all(client, headers, leads):
    assert await _ids(client, headers, {}) == [1, 2, 3, 4, 5, 6]


async def test_count_matches_list(client, headers, leads):
    """Счётчик «Найдено» считает то же, что вернул список."""
    resp = await client.get(
        "/api/chat/dialogs/count", headers=headers, params={"marketing_tag": "sweetgold"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


async def test_csv_export_filtered_by_tag(client, headers, leads):
    """Выгрузка ходит через ту же функцию фильтров и знает про метку."""
    resp = await client.get(
        "/api/chat/dialogs/export", headers=headers, params={"marketing_tag": "sweetgold"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "marketing_tag" in body.splitlines()[0]
    assert body.count("sweetgold") == 2
    assert "ПАВЕЛ_ПАТРИОТ_1" not in body


async def test_export_ids_filtered_by_tag(client, headers, leads):
    resp = await client.get(
        "/api/chat/dialogs/export-ids", headers=headers, params={"marketing_tag": "sweetgold"},
    )
    assert resp.status_code == 200
    assert sorted(resp.text.split(";")) == ["1", "2"]


async def test_tag_list_sorted_by_usage(client, headers, leads):
    """Сверху — метка с бóльшим числом диалогов; клиентов без метки в списке нет."""
    resp = await client.get("/api/chat/marketing-tags", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == ["sweetgold", "hood141", "ПАВЕЛ_ПАТРИОТ_1"]


async def test_tag_list_respects_dialog_type_access(client, db, leads):
    """Куратор своего направления не видит в фильтре метки чужого."""
    user = User(
        email="curator@test.io", password_hash=hash_password("pass1234"),
        role=UserRole.curator,
    )
    db.add(user)
    await db.flush()
    db.add(UserDialogType(user_id=user.id, type_id=1))
    await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": "curator@test.io", "password": "pass1234"},
    )
    hdrs = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = await client.get("/api/chat/marketing-tags", headers=hdrs)
    assert resp.status_code == 200
    assert resp.json() == ["sweetgold", "ПАВЕЛ_ПАТРИОТ_1"]
