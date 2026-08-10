"""В списке лидов видно имя и фамилию, а не числовой VK ID.

ОП, 10 августа, 16:16: «имя фамилия надо вывести в лидах вместо айди».

Имя и фамилия хранятся раздельно намеренно: `clients.name` — это форма обращения
в диалоге, а по фамилии обращаться нельзя («Соколова, здравствуйте» звучит как
повестка, см. app.utils.text.usable_name). Полное имя собирается только для
интерфейса.
"""
import pytest
from sqlalchemy import select

from app.auth.service import hash_password
from app.db.models import Client, Dialog, DialogType, User, UserRole
from app.utils.text import usable_name


@pytest.fixture
async def headers(client, db):
    db.add(User(email="boss@test.io", password_hash=hash_password("pass1234"), role=UserRole.admin))
    await db.commit()
    resp = await client.post("/api/auth/login", json={"email": "boss@test.io", "password": "pass1234"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def lead(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    c = Client(vk_user_id=227963806, name="Анастасия", last_name="Хананова")
    db.add(c)
    await db.flush()
    db.add(Dialog(client_id=c.id, type_id=1, is_test=False))
    await db.commit()
    return c


async def test_dialog_list_carries_both_parts_of_the_name(client, headers, lead):
    resp = await client.get("/api/chat/dialogs", headers=headers)

    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["client_name"] == "Анастасия"
    assert row["client_last_name"] == "Хананова"
    assert row["vk_user_id"] == 227963806


async def test_surname_never_becomes_a_form_of_address(lead):
    """Фамилия живёт отдельно как раз для того, чтобы не попасть в обращение."""
    assert usable_name(lead.name) == "Анастасия"
    assert usable_name(lead.last_name) is None


async def test_csv_export_has_a_surname_column(client, headers, lead):
    resp = await client.get("/api/chat/dialogs/export", headers=headers)

    assert resp.status_code == 200
    body = resp.text
    assert "client_last_name" in body.splitlines()[0]
    assert "Хананова" in body
