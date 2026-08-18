"""Перезаливка фото с внешних URL на своё сообщество ВК.

VK принимает attachment в messages.send только на объекты, принадлежащие токену
отправителя (своему сообществу) или загруженные через его upload-сервер — фото с
чужого URL (Wazzup24, товарная матрица) нужно один раз скачать и перезалить.
Результат кэшируется в vk_attachment_cache по (vk_group_id, source_url).
"""
import logging

import httpx
from sqlalchemy import delete, select
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


async def upload_doc_for_messages(
    access_token: str, data: bytes, filename: str, peer_id: int | None = None,
) -> str:
    """Залить файл документом сообщества и вернуть «doc<owner>_<id>».

    Видео и всё, что не картинка, ВК принимает во вложение только так: у
    photos-загрузчика для сообщений другой формат.
    """
    params = {"type": "doc"}
    if peer_id:
        params["peer_id"] = peer_id
    info = await vk_api_call(access_token, "docs.getMessagesUploadServer", params)
    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
        resp = await client.post(
            info["upload_url"], files={"file": (filename, data)},
        )
    resp.raise_for_status()
    uploaded = resp.json()
    if not uploaded.get("file"):
        raise RuntimeError(f"upload server returned no file: {uploaded}")
    saved = await vk_api_call(
        access_token, "docs.save", {"file": uploaded["file"], "title": filename},
    )
    doc = saved.get("doc") if isinstance(saved, dict) else saved[0]
    return f"doc{doc['owner_id']}_{doc['id']}"


async def resolve_doc(
    db: AsyncSession, group: VkGroup, source_url: str, peer_id: int | None = None,
) -> str | None:
    """Кэш + перезалив документом. None, если не удалось."""
    cached = await db.scalar(
        select(VkAttachmentCache).where(
            VkAttachmentCache.vk_group_id == group.id,
            VkAttachmentCache.source_url == source_url,
        )
    )
    if cached:
        return cached.attachment
    filename = source_url.split("?", 1)[0].rsplit("/", 1)[-1] or "file"
    try:
        data = await download_image(source_url)
        attachment = await upload_doc_for_messages(
            group.access_token, data, filename, peer_id,
        )
    except Exception as e:
        logger.warning("resolve_doc failed | url=%s | error=%s", source_url, e)
        return None
    db.add(VkAttachmentCache(vk_group_id=group.id, source_url=source_url, attachment=attachment))
    await db.commit()
    logger.info("resolve_doc: uploaded+cached | group=%s | attachment=%s", group.id, attachment)
    return attachment


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


async def forget_attachments(db: AsyncSession, group_id: int, attachments: list[str]) -> int:
    """Забыть перезалитые объекты — следующая отправка зальёт их заново.

    Кэш живёт вечно, а объект в ВК — нет: залитые 5 августа картинки к скриптам
    «2.2 Стоимость» и «5. Оформление» умерли 8 августа, и с тех пор `messages.send`
    молча выбрасывал их из каждого сообщения. Клиенты десять дней получали цену
    без фото товара и оформление без отзывов, а в базе стояло `delivered: true`.
    """
    if not attachments:
        return 0
    result = await db.execute(
        delete(VkAttachmentCache).where(
            VkAttachmentCache.vk_group_id == group_id,
            VkAttachmentCache.attachment.in_(attachments),
        )
    )
    await db.commit()
    return result.rowcount or 0
