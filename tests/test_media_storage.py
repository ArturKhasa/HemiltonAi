"""Файлы из админки лежат на сервере, а не в S3.

Ради нескольких картинок в тестовых диалогах внешнее хранилище с ключами в .env
не нужно: каталог смонтирован томом рядом с логами и переживает деплой.
"""
import pytest

from app.config import settings
from app.storage import local


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_URL", "", raising=False)
    return tmp_path


class TestSaveFile:
    @pytest.mark.asyncio
    async def test_file_lands_on_disk(self, media_dir):
        url = await local.save_file(b"\x89PNG data", "chat/12/abc.png")
        assert (media_dir / "chat/12/abc.png").read_bytes() == b"\x89PNG data"
        assert url == "/media/chat/12/abc.png"

    @pytest.mark.asyncio
    async def test_public_url_is_absolute_when_domain_is_set(self, media_dir, monkeypatch):
        """Ссылку читают модель и ВК — относительный адрес им не годится."""
        monkeypatch.setattr(settings, "MEDIA_PUBLIC_URL", "https://ai.example.ru/", raising=False)
        url = await local.save_file(b"x", "chat/1/a.jpg")
        assert url == "https://ai.example.ru/media/chat/1/a.jpg"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", [
        "chat/../../etc/passwd.jpg",
        "chat/12/../../../root.jpg",
        "/etc/passwd",
        "chat/12/файл.jpg",
        "chat/12/a b.jpg",
    ])
    async def test_path_traversal_is_refused(self, media_dir, key):
        with pytest.raises(RuntimeError):
            await local.save_file(b"x", key)


class TestSafeExtension:
    @pytest.mark.parametrize("filename,expected", [
        ("photo.JPG", "jpg"),
        ("дизайн.png", "png"),
        ("clip.mp4", "mp4"),
        ("чек.pdf", "pdf"),
        ("no-extension", "bin"),
        (None, "bin"),
    ])
    def test_known_kinds_keep_their_extension(self, filename, expected):
        assert local.safe_extension(filename) == expected

    @pytest.mark.parametrize("filename", ["evil.html", "evil.svg", "evil.js", "shell.php"])
    def test_scriptable_kinds_become_bin(self, filename):
        """Каталог отдаётся статикой: «.html» с нашего домена — скрипт в контексте
        админки, а «.svg» умеет то же самое."""
        assert local.safe_extension(filename) == "bin"
