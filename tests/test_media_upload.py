"""Загрузка картинки файлом: POST /api/media/upload.

Картинки приветствий добавляли только ссылкой, а чтобы получить ссылку, файл
надо было сначала куда-то выложить. Теперь он кладётся на наш сервер и сразу
получает адрес, по которому его читают браузер админки, модель и ВК.
"""
import pytest

from app.auth.service import hash_password
from app.config import settings
from app.db.models import User, UserRole


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_URL", "", raising=False)
    return tmp_path


async def _headers(client, db, email, role):
    db.add(User(email=email, password_hash=hash_password("pass1234"), role=role))
    await db.commit()
    resp = await client.post("/api/auth/login", json={"email": email, "password": "pass1234"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def admin_headers(client, db):
    return await _headers(client, db, "boss@test.io", UserRole.admin)


async def test_uploaded_image_lands_on_disk(client, db, admin_headers, media_dir):
    resp = await client.post(
        "/api/media/upload", headers=admin_headers,
        files={"file": ("дизайн.png", b"\x89PNG picture", "image/png")},
    )
    assert resp.status_code == 200
    url = resp.json()["url"]
    assert url.startswith("/media/greeting/") and url.endswith(".png")
    assert (media_dir / url.removeprefix("/media/")).read_bytes() == b"\x89PNG picture"


async def test_url_is_absolute_for_vk_and_the_model(client, db, admin_headers, media_dir, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_URL", "https://ai.example.ru", raising=False)
    resp = await client.post(
        "/api/media/upload", headers=admin_headers,
        files={"file": ("a.jpg", b"jpeg", "image/jpeg")},
    )
    assert resp.json()["url"].startswith("https://ai.example.ru/media/greeting/")


async def test_two_uploads_do_not_collide(client, db, admin_headers, media_dir):
    urls = set()
    for _ in range(2):
        resp = await client.post(
            "/api/media/upload", headers=admin_headers,
            files={"file": ("same-name.jpg", b"jpeg", "image/jpeg")},
        )
        urls.add(resp.json()["url"])
    assert len(urls) == 2


async def test_empty_file_refused(client, db, admin_headers, media_dir):
    resp = await client.post(
        "/api/media/upload", headers=admin_headers,
        files={"file": ("a.jpg", b"", "image/jpeg")},
    )
    assert resp.status_code == 400


async def test_scriptable_file_refused(client, db, admin_headers, media_dir):
    """Каталог отдаётся статикой — «.html» с нашего домена это скрипт в админке."""
    resp = await client.post(
        "/api/media/upload", headers=admin_headers,
        files={"file": ("evil.html", b"<script>", "text/html")},
    )
    assert resp.status_code == 400
    assert not list(media_dir.rglob("*"))


async def test_oversized_file_refused(client, db, admin_headers, media_dir, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_MAX_UPLOAD_MB", 1, raising=False)
    resp = await client.post(
        "/api/media/upload", headers=admin_headers,
        files={"file": ("big.jpg", b"x" * (1024 * 1024 + 1), "image/jpeg")},
    )
    assert resp.status_code == 413


async def test_anonymous_cannot_upload(client, db, media_dir):
    resp = await client.post(
        "/api/media/upload",
        files={"file": ("a.jpg", b"jpeg", "image/jpeg")},
    )
    assert resp.status_code in (401, 403)
