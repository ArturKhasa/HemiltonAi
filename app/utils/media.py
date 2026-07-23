"""Классификация URL вложений + content-hash дедуп исходящих изображений.

ВК перезаливает одно и то же фото под новым URL, поэтому сравнение по строке URL
пропускает дубли — хэшируем байты изображения.
"""
import asyncio
import hashlib
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_HASH_TIMEOUT = 10.0

_AUDIO_EXTENSIONS = frozenset([".mp3", ".ogg", ".wav", ".m4a", ".aac", ".oga", ".opus", ".flac"])
# Голосовые ВК приходят как URL без расширения (.../vk/audio/get/<base64>),
# поэтому одного матчинга расширений мало.
_AUDIO_PATHS = ("/vk/audio/get/", "/audio/get/")


def is_audio_url(url: str) -> bool:
    lower = url.lower().split("?")[0]
    if any(path in lower for path in _AUDIO_PATHS):
        return True
    return any(lower.endswith(ext) for ext in _AUDIO_EXTENSIONS)


_VIDEO_EXTENSIONS = frozenset([".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".3gp"])
_VIDEO_HOSTS = ("vkvideo.ru", "vk.com/video", "vk.ru/video")


def is_video_url(url: str) -> bool:
    lower = url.lower().split("?")[0]
    if any(lower.endswith(ext) for ext in _VIDEO_EXTENSIONS):
        return True
    return any(host in lower for host in _VIDEO_HOSTS)


_STICKER_HOSTS = ("vk.ru/sticker/", "vk.com/sticker/", "vkontakte.ru/sticker/")


def is_sticker_url(url: str) -> bool:
    lower = url.lower()
    return any(pat in lower for pat in _STICKER_HOSTS)


def is_image_url(url: str) -> bool:
    """True только для URL, безопасных для vision-модели как input_image.

    Исключает стикеры, аудио (голосовые) и видео — такие вложения vision-модели
    отклоняют с 'invalid image content'.
    """
    return not (is_sticker_url(url) or is_audio_url(url) or is_video_url(url))


async def _hash_one(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return hashlib.sha256(resp.content).hexdigest()
    except Exception as exc:
        logger.warning("image hash fetch failed | url=%.80s | err=%s", url, exc)
        return None


async def hash_image_urls(urls: list[str]) -> dict[str, str]:
    """Map each fetchable URL -> sha256 of its bytes. Failed/empty URLs omitted."""
    unique = list(dict.fromkeys(u for u in urls if u))
    if not unique:
        return {}
    async with httpx.AsyncClient(timeout=_HASH_TIMEOUT, follow_redirects=True) as client:
        hashes = await asyncio.gather(*(_hash_one(client, u) for u in unique))
    return {u: h for u, h in zip(unique, hashes) if h}


async def collect_sent_image_hashes(db: AsyncSession, dialog_id: int) -> set[str]:
    """Content hashes of all images already sent by AI/curator in this dialog.

    Uses the stored `file_hashes` metadata when present; for older messages that
    only recorded `files` URLs, fetches and hashes them lazily (best effort).
    """
    from app.db.models import Message, MessageRole

    rows = await db.execute(
        select(Message.msg_metadata).where(
            Message.dialog_id == dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
    )
    hashes: set[str] = set()
    pending: list[str] = []
    for (meta,) in rows.all():
        if not meta:
            continue
        stored = meta.get("file_hashes")
        if stored:
            hashes.update(stored)
        else:
            pending.extend(meta.get("files") or [])
    if pending:
        hashes.update((await hash_image_urls(pending)).values())
    return hashes
