"""Классификация URL вложений + content-hash дедуп исходящих изображений.

ВК перезаливает одно и то же фото под новым URL, поэтому сравнение по строке URL
пропускает дубли — хэшируем байты изображения.
"""
import asyncio
import hashlib
import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ssl_trust import async_client

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


# Документы (VK attachment type "doc") — чеки/файлы, которые клиент прислал не как
# фото. Не все расширения — картинки (см. is_image_url), но URL всё равно нужно
# сохранить в msg_metadata.files, чтобы куратор мог открыть файл вручную.
_DOCUMENT_EXTENSIONS = frozenset([
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".txt", ".csv",
])


def is_document_url(url: str) -> bool:
    lower = url.lower().split("?")[0]
    return any(lower.endswith(ext) for ext in _DOCUMENT_EXTENSIONS)


def is_image_url(url: str) -> bool:
    """True только для URL, безопасных для vision-модели как input_image.

    Исключает стикеры, аудио (голосовые), видео и документы (pdf/doc/...) — такие
    вложения vision-модели отклоняют с 'invalid image content'.
    """
    return not (is_sticker_url(url) or is_audio_url(url) or is_video_url(url) or is_document_url(url))


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
    async with async_client(timeout=_HASH_TIMEOUT, follow_redirects=True) as client:
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


# Токены вложений внутри текста фразы: «[photo-<url>]», «[photo-<id>_<id>]»,
# а также video/clip/audio_message/doc. Их разбирает app.vk.sender при отправке.
# Дефис необязателен: голосовые в выгрузке ОП записаны без него —
# «[audio_message569993513_687712211]».
#
# «doc» — видео, pdf и аудио, загруженные в скрипт файлом (ОП, 03.09: «добавьте
# возможность добавлять видео в скрипты»). Без него такой токен не считался
# вложением: редактор скриптов оставлял его в тексте, модель видела его среди
# слов и теряла при пересказе.
_ATTACHMENT_TOKEN_RE = re.compile(r"\[(?:photo|video|clip|audio_message|doc)-?[^\]\s]+\]")

# Ссылка в токене со всеми параметрами длиной под три сотни символов, и модель
# переписывает её с ошибкой: в диалоге 91 она потеряла половину «attachment=
# photo-44440184_457423551» в самом хвосте. Токен переставал совпадать со
# скриптовым посимвольно, скриптовый дописывался как «потерянный», и клиент
# получал одну и ту же вешалку с цветами дважды. Сравниваем по адресу без
# query: параметры кадрирования на то, какая это картинка, не влияют.
_TOKEN_URL_RE = re.compile(r"\[(photo|video|clip|audio_message|doc)-?(https?://[^\]?]+)")


def attachment_tokens(text: str | None) -> list[str]:
    """Токены вложений из текста фразы, по порядку."""
    return _ATTACHMENT_TOKEN_RE.findall(text or "")


def strip_attachment_tokens(text: str | None) -> str:
    """Текст без токенов вложений — то, что клиент реально прочитает."""
    return _ATTACHMENT_TOKEN_RE.sub("", text or "").strip()


def _attachment_key(token: str) -> str:
    m = _TOKEN_URL_RE.match(token)
    return f"{m.group(1)}:{m.group(2)}" if m else token


def carry_over_attachments(text: str, source_text: str) -> str:
    """Вернуть в текст вложения исходной фразы, которые модель из неё выбросила.

    И продающий агент, и пинговый переписывают готовую фразу своими словами и
    теряют при этом токены вложений: из 70 отправленных пингов с медиа 33 ушли
    без единой картинки, хотя в правиле она была. Смысл фразы модель сохраняет,
    а вложение для неё — посторонний мусор в конце.

    Токены дописываются одним блоком в конец: ВК показывает вложения отдельно от
    текста, и место токена внутри сообщения ни на что не влияет.
    """
    present = {_attachment_key(t) for t in _ATTACHMENT_TOKEN_RE.findall(text or "")}
    missing: list[str] = []
    for token in _ATTACHMENT_TOKEN_RE.findall(source_text or ""):
        key = _attachment_key(token)
        if key in present:
            continue
        present.add(key)
        missing.append(token)
    if not missing:
        return text
    return (text or "").rstrip() + "\n\n" + "\n".join(missing)

# Картинку ВК принимает фотографией, всё остальное — только документом
# (см. app.vk.photo_upload.resolve_doc). Расширение берём из имени файла в
# ссылке: своё хранилище кладёт файлы как «<uuid>.<ext>».
_IMAGE_EXTENSIONS = frozenset(("jpg", "jpeg", "png", "gif", "webp", "heic"))


def attachment_token(url: str) -> str:
    """Токен вложения для ссылки: [photo-…] для картинки, [doc-…] для файла."""
    name = (url or "").split("?", 1)[0].rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return f"[{'photo' if ext in _IMAGE_EXTENSIONS else 'doc'}-{url}]"
