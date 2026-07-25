"""Перезаливка фото с внешних URL на своё сообщество ВК.

VK принимает attachment в messages.send только на объекты, принадлежащие токену
отправителя (своему сообществу) или загруженные через его upload-сервер — фото с
чужого URL (Wazzup24, товарная матрица) нужно один раз скачать и перезалить.
Результат кэшируется в vk_attachment_cache по (vk_group_id, source_url).
"""
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VkAttachmentCache, VkGroup
from app.vk.sender import vk_api_call

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT = 20.0
_UPLOAD_TIMEOUT = 30.0


async def download_image(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
    resp.raise_for_status()
    return resp.content


async def upload_photo_for_messages(access_token: str, image_bytes: bytes, filename: str = "photo.jpg") -> str:
    """Загружает фото на upload-сервер СВОЕГО сообщества и возвращает attachment-строку
    ("photo<owner_id>_<id>"), пригодную для messages.send этим же токеном."""
    upload_info = await vk_api_call(access_token, "photos.getMessagesUploadServer", {})
    upload_url = upload_info["upload_url"]
    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
        resp = await client.post(upload_url, files={"photo": (filename, image_bytes, "image/jpeg")})
    resp.raise_for_status()
    data = resp.json()
    result = await vk_api_call(access_token, "photos.saveMessagesPhoto", {
        "photo": data["photo"], "server": data["server"], "hash": data["hash"],
    })
    photo = result[0]
    return f"photo{photo['owner_id']}_{photo['id']}"


async def resolve_attachment(db: AsyncSession, group: VkGroup, source_url: str) -> str | None:
    """Кэш + перезалив: attachment-строка для source_url на КОНКРЕТНОЕ сообщество.
    None, если скачать/перезалить не удалось (клиенту тогда уходит текст без фото —
    лучше, чем упавшая отправка всего сообщения)."""
    cached = await db.scalar(
        select(VkAttachmentCache).where(
            VkAttachmentCache.vk_group_id == group.id,
            VkAttachmentCache.source_url == source_url,
        )
    )
    if cached:
        return cached.attachment
    try:
        image_bytes = await download_image(source_url)
        attachment = await upload_photo_for_messages(group.access_token, image_bytes)
    except Exception as e:
        logger.warning("resolve_attachment failed | url=%s | error=%s", source_url, e)
        return None
    db.add(VkAttachmentCache(vk_group_id=group.id, source_url=source_url, attachment=attachment))
    await db.commit()
    logger.info("resolve_attachment: uploaded+cached | group=%s | url=%s | attachment=%s", group.id, source_url, attachment)
    return attachment
