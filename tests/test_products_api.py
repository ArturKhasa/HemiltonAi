"""Товарная матрица в админке: список и стоп на позицию.

Экрана и эндпоинта у матрицы не было вовсе — её заводили выгрузкой и правили
руками в базе. Понадобились они ради одной задачи: Лена, 04.09, «распродали
один из цветов для свитшотов... как поставить определённый цвет на стоп?».
Рычаг (`Product.is_active`) в коде был, дотянуться до него из панели — нельзя.
"""
import pytest

from app.auth.service import hash_password
from app.db.models import DialogType, Product, User, UserRole


@pytest.fixture
async def admin_headers(client, db):
    db.add(User(
        email="boss@test.io", password_hash=hash_password("pass1234"),
        role=UserRole.admin,
    ))
    await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": "boss@test.io", "password": "pass1234"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def matrix(db):
    db.add(DialogType(id=1, name="default", display_name="Основное"))
    db.add_all([
        Product(id=1, type_id=1, name="Свитшот Черный", price=5990, is_active=True),
        Product(id=2, type_id=1, name="Свитшот Бежевый", price=5990, is_active=True),
    ])
    await db.commit()
    return db


class TestListProducts:
    async def test_admin_sees_the_matrix(self, client, matrix, admin_headers):
        res = await client.get("/api/products/", headers=admin_headers)

        assert res.status_code == 200
        names = [p["name"] for p in res.json()]
        assert names == ["Свитшот Черный", "Свитшот Бежевый"]

    async def test_deactivated_rows_are_still_listed(self, client, matrix, admin_headers):
        """Снятая позиция из панели не пропадает — иначе вернуть её было бы нечем."""
        product = await matrix.get(Product, 1)
        product.is_active = False
        await matrix.commit()

        res = await client.get("/api/products/", headers=admin_headers)

        assert res.status_code == 200
        assert [p["is_active"] for p in res.json()] == [False, True]

    async def test_anonymous_is_turned_away(self, client, matrix):
        assert (await client.get("/api/products/")).status_code == 401


class TestToggleProduct:
    async def test_color_goes_out_of_stock(self, client, matrix, admin_headers):
        res = await client.patch(
            "/api/products/1", json={"is_active": False}, headers=admin_headers,
        )

        assert res.status_code == 200
        assert res.json()["is_active"] is False
        assert (await matrix.get(Product, 1)).is_active is False

    async def test_color_comes_back(self, client, matrix, admin_headers):
        product = await matrix.get(Product, 1)
        product.is_active = False
        await matrix.commit()

        res = await client.patch(
            "/api/products/1", json={"is_active": True}, headers=admin_headers,
        )

        assert res.status_code == 200
        assert res.json()["is_active"] is True

    async def test_missing_product(self, client, matrix, admin_headers):
        res = await client.patch(
            "/api/products/999", json={"is_active": False}, headers=admin_headers,
        )
        assert res.status_code == 404
