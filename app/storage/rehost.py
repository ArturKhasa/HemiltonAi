"""Картинки скриптов и пингов держим у себя, а не ссылками на чужой CDN.

Ссылка на `sun9-…vkuserphoto.ru` умирает молча: перезалитый по ней объект ВК
перестаёт существовать, `messages.send` продолжает принимать его без ошибки и
просто не кладёт в сообщение. С 8 августа так ушли 85 сообщений с ценой и 28 с
оформлением — все без картинок, и ни одна проверка в коде этого не заметила.
Картинки приветствия лежат у нас и не потерялись ни разу.

Поэтому внешнюю ссылку в тексте скрипта или пинг-правила забираем себе сразу
при сохранении из админки. Не скачалось — оставляем ссылку как есть: картинка
по ней, возможно, ещё живёт, а выбросить её значит потерять наверняка.
"""
import logging
import re
import uuid

import httpx

from app.ssl_trust import async_client
from app.storage.local import safe_extension, save_file

logger = logging.getLogger(__name__)

_PHOTO_URL_TOKEN_RE = re.compile(r"\[photo-(https?://[^\]]+)\]")
# Наши же ссылки трогать незачем.
_OURS_RE = re.compile(r"/media/", re.I)

_DOWNLOAD_TIMEOUT = 20.0
# Картинка скрипта — фотография изделия; всё, что заметно больше, это не она.
_MAX_BYTES = 25 * 1024 * 1024


def external_photo_urls(text: str) -> list[str]:
    """Чужие ссылки на картинки в тексте, по одному разу каждая."""
    seen: list[str] = []
    for url in _PHOTO_URL_TOKEN_RE.findall(text or ""):
        if not _OURS_RE.search(url) and url not in seen:
            seen.append(url)
    return seen


def _extension(url: str) -> str:
    """Расширение из имени файла в ссылке; у ВК оно есть до «?»."""
    name = url.split("?", 1)[0].rsplit("/", 1)[-1]
    ext = safe_extension(name)
    return "jpg" if ext == "bin" else ext


async def fetch_and_store(url: str) -> str | None:
    """Скачать картинку и положить к себе. Ссылка на наш файл, либо None."""
    try:
        async with async_client(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content
    except Exception as exc:
        logger.warning("картинку не забрать, остаётся внешней ссылкой | %s: %s", url[:70], exc)
        return None
    if not data or len(data) > _MAX_BYTES:
        logger.warning("картинка пустая или слишком большая | %s | %d байт", url[:70], len(data))
        return None
    ours = await save_file(data, f"scripts/{uuid.uuid4().hex}.{_extension(url)}")
    logger.info("картинка перенесена к нам | %d КБ | %s", len(data) // 1024, ours)
    return ours


async def rehost_external_photos(text: str, cache: dict[str, str] | None = None) -> str:
    """Текст, в котором чужие ссылки на картинки заменены нашими.

    cache — общий словарь «чужая ссылка → наша» на пачку текстов: одна и та же
    картинка стоит в нескольких скриптах, качать её повторно незачем.
    """
    urls = external_photo_urls(text)
    if not urls:
        return text
    cache = cache if cache is not None else {}
    for url in urls:
        ours = cache.get(url) or await fetch_and_store(url)
        if ours is None:
            continue
        cache[url] = ours
        text = text.replace(f"[photo-{url}]", f"[photo-{ours}]")
    return text
