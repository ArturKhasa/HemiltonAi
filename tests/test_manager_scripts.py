"""Выбор скрипта при ответе менеджера.

Пункт 5 обоих списков с созвона 27.08. Менеджеры работают в BlueSales, а
интеграции с ней не будет (решение 27.08) — значит отвечать надо из панели, и
теми же фразами, что у ИИ, а не по памяти.

Текст отдаётся с теми же подстановками, что у автоматической отправки: иначе
менеджер вставил бы клиенту «[цена:свитшот]» и «[Имя]».
"""
import pytest

from app.auth.service import hash_password
from app.db.models import (
    Client, Dialog, DialogType, Message, MessageRole, Product, Script, User, UserRole,
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
async def dialog(db):
    db.add_all([
        DialogType(id=1, name="default", display_name="Основное"),
        DialogType(id=2, name="opt", display_name="Опт"),
    ])
    db.add(Product(name="свитшот", type_id=1, price=5990, min_price=4990, is_active=True))
    db.add_all([
        Script(id=367, is_active=True, type_id=1, funnel_stage="pricing",
               condition="2.2 Стоимость (свитшот). Уходит связкой сразу после похвалы",
               phrase_text="[Имя], стоимость толстовки со скидкой - [цена:свитшот]\n"
                           "[photo-https://ai.hemilton.ru/media/scripts/a.jpg]"),
        Script(id=372, is_active=True, type_id=1, funnel_stage="design",
               condition="2.3 Доставка", phrase_text="В какой город нужна доставка?"),
        Script(id=400, is_active=False, type_id=1, condition="Выключенный",
               phrase_text="Не показывать"),
        Script(id=500, is_active=True, type_id=2, condition="Чужое направление",
               phrase_text="Оптовый скрипт"),
    ])
    await db.flush()
    c = Client(vk_user_id=555, name="Алексей")
    db.add(c)
    await db.flush()
    d = Dialog(client_id=c.id, type_id=1, is_test=False)
    db.add(d)
    await db.flush()
    db.add(Message(dialog_id=d.id, role=MessageRole.client, text="Смирнов"))
    await db.commit()
    return d


class TestList:
    async def test_lists_active_scripts_of_this_direction(self, client, headers, dialog):
        resp = await client.get(f"/api/chat/dialogs/{dialog.id}/scripts", headers=headers)
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()]
        assert 367 in ids and 372 in ids
        assert 400 not in ids          # выключен
        assert 500 not in ids          # чужое направление

    async def test_label_is_the_first_line_of_the_condition(self, client, headers, dialog):
        resp = await client.get(f"/api/chat/dialogs/{dialog.id}/scripts", headers=headers)
        by_id = {s["id"]: s for s in resp.json()}
        assert by_id[367]["label"].startswith("2.2 Стоимость")
        assert by_id[367]["funnel_stage"] == "pricing"

    async def test_preview_has_no_attachment_tokens(self, client, headers, dialog):
        """В превью списка токен «[photo-…]» — мусор на пол-строки."""
        resp = await client.get(f"/api/chat/dialogs/{dialog.id}/scripts", headers=headers)
        by_id = {s["id"]: s for s in resp.json()}
        assert "[photo-" not in by_id[367]["preview"]

    async def test_order_follows_the_funnel(self, client, headers, dialog):
        resp = await client.get(f"/api/chat/dialogs/{dialog.id}/scripts", headers=headers)
        ids = [s["id"] for s in resp.json()]
        assert ids.index(367) < ids.index(372)   # pricing раньше design

    async def test_unknown_dialog(self, client, headers):
        resp = await client.get("/api/chat/dialogs/424242/scripts", headers=headers)
        assert resp.status_code == 404


class TestRender:
    async def test_substitutions_are_applied(self, client, headers, dialog):
        resp = await client.get(
            f"/api/chat/dialogs/{dialog.id}/scripts/367", headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Алексей" in body["text"]
        # Цена печатается с неразрывным пробелом: сумма не должна рваться переносом.
        assert "5\u00a0990" in body["text"]
        assert "[Имя]" not in body["text"] and "[цена:" not in body["text"]

    async def test_photos_go_to_attachments_not_text(self, client, headers, dialog):
        """Ссылка текстом читается клиентом как набор символов — картинки
        уходят вложением, как и у ИИ."""
        body = (await client.get(
            f"/api/chat/dialogs/{dialog.id}/scripts/367", headers=headers,
        )).json()
        assert body["files"] == ["https://ai.hemilton.ru/media/scripts/a.jpg"]
        assert "photo-" not in body["text"]

    async def test_preview_does_not_pin_the_price(self, client, headers, dialog, db):
        """Менеджер мог открыть скрипт и передумать: от одного просмотра цена
        диалога меняться не должна."""
        await client.get(f"/api/chat/dialogs/{dialog.id}/scripts/367", headers=headers)
        await db.refresh(dialog)
        assert not (dialog.quoted_prices or {})

    async def test_inactive_script_is_not_rendered(self, client, headers, dialog):
        resp = await client.get(
            f"/api/chat/dialogs/{dialog.id}/scripts/400", headers=headers,
        )
        assert resp.status_code == 404

    async def test_unknown_script(self, client, headers, dialog):
        resp = await client.get(
            f"/api/chat/dialogs/{dialog.id}/scripts/999999", headers=headers,
        )
        assert resp.status_code == 404
