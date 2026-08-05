"""Файлы, загруженные из админки, — на диске рядом с приложением.

Раньше они уходили в S3. Ради нескольких картинок в тестовых диалогах это лишний
внешний сервис с ключами в .env: отдать их умеет и сам сервер, каталог живёт в
томе рядом с логами и переживает деплой.

Ссылку возвращаем абсолютную, если задан MEDIA_PUBLIC_URL: файл читает не только
браузер админа, но и модель (картинку сообщения она получает по URL) и ВК, когда
перезаливает фото из токена. Относительный адрес им не годится.
"""
import asyncio
import re
from pathlib import Path

from app.config import settings

# Отдаём каталог статикой, поэтому расширение решает, с каким Content-Type файл
# уйдёт браузеру. «.html» и «.svg» с нашего домена — это скрипт в контексте
# админки, поэтому список закрытый, всё остальное сохраняем как .bin.
_ALLOWED_EXTENSIONS = frozenset(
    ("jpg", "jpeg", "png", "gif", "webp", "heic", "mp4", "mov", "pdf", "ogg", "mp3", "m4a")
)

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def media_root() -> Path:
    root = Path(settings.MEDIA_ROOT)
    if not root.is_absolute():
        root = Path(__file__).resolve().parent.parent.parent / root
    return root


def safe_extension(filename: str | None) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    return ext if ext in _ALLOWED_EXTENSIONS else "bin"


def public_url(key: str) -> str:
    base = settings.MEDIA_PUBLIC_URL.rstrip("/")
    return f"{base}/media/{key}" if base else f"/media/{key}"


async def save_file(data: bytes, key: str, content_type: str = "image/jpeg") -> str:
    """Сохранить файл под ключом «chat/<dialog_id>/<uuid>.jpg» и вернуть ссылку.

    content_type не сохраняем: статика отдаёт его по расширению.
    """
    # «..» шаблону соответствует — точка в нём разрешена ради расширения, — поэтому
    # переходы наверх отсекаем отдельно.
    parts = key.split("/")
    if not parts or any(
        p in ("", ".", "..") or not _SAFE_SEGMENT_RE.match(p) for p in parts
    ):
        raise RuntimeError(f"Недопустимое имя файла: {key!r}")

    path = media_root() / key
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, data)
    return public_url(key)
