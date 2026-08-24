"""Отправка сообщений клиенту в MAX.

Вложения тут проще, чем в ВК: MAX забирает картинку по внешней ссылке сам, и
перезаливать её на свою сторону (app.vk.photo_upload) не нужно. Токены в тексте
фразы те же самые — «[photo-<url>]», «[doc-<url>]», «[video-<url>]», — их
пишут и импортированные из старой CRM фразы, и панель менеджера.
"""
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Dialog, VkGroup
from app.max.client import (
    MaxApiError, MaxMessagesForbiddenError, MaxSentMessage, send_message, upload_media,
)

logger = logging.getLogger(__name__)

# Сколько вложений MAX принимает в одном сообщении (изображения и видео
# суммарно, см. PhotoAttachmentRequestPayload).
_MAX_ATTACHMENTS = 12

_PHOTO_URL_TOKEN_RE = re.compile(r"\[photo-(https?://[^\]]+)\]")
_DOC_URL_TOKEN_RE = re.compile(r"\[doc-(https?://[^\]]+)\]")
_VIDEO_URL_TOKEN_RE = re.compile(r"\[video-(https?://[^\]]+)\]")
# Токен без ссылки: мёртвый VK-id из старых фраз («[photo-44440184_457423551]»)
# или выдумка модели («[photo-фиолетовый свитшот]»). В MAX прикрепить по нему
# нечего — вырезаем, чтобы клиент не читал квадратные скобки.
_JUNK_TOKEN_RE = re.compile(r"\[(?:photo|video|clip|audio_message)-?[^\]\n]*\]")


def build_attachments(text: str) -> tuple[str, list[dict]]:
    """Разобрать вложения в тексте фразы: вернуть (текст без токенов, вложения).

    Сначала пробуем отдать MAX внешнюю ссылку — так вложение уходит одним
    запросом. Заливка через /uploads остаётся запасным путём для ссылок,
    которые MAX забрать не смог.
    """
    attachments: list[dict] = []

    def _collect(pattern: re.Pattern, att_type: str, source: str) -> str:
        for m in pattern.finditer(source):
            attachments.append({"type": att_type, "payload": {"url": m.group(1)}})
        return pattern.sub("", source)

    cleaned = _collect(_PHOTO_URL_TOKEN_RE, "image", text or "")
    cleaned = _collect(_VIDEO_URL_TOKEN_RE, "video", cleaned)
    cleaned = _collect(_DOC_URL_TOKEN_RE, "file", cleaned)

    junk = _JUNK_TOKEN_RE.findall(cleaned)
    if junk:
        logger.warning("MAX: токены вложений без ссылки вырезаны | %s", junk[:3])
        cleaned = _JUNK_TOKEN_RE.sub("", cleaned)

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(attachments) > _MAX_ATTACHMENTS:
        logger.warning(
            "MAX: вложений %d, отправляем первые %d", len(attachments), _MAX_ATTACHMENTS,
        )
        attachments = attachments[:_MAX_ATTACHMENTS]
    return cleaned, attachments


_UPLOAD_TYPE_BY_ATTACHMENT = {"image": "image", "video": "video", "file": "file"}


async def _reupload(token: str, attachments: list[dict]) -> list[dict]:
    """Залить вложения в MAX своими руками — ссылку он не принял.

    То, что залить не удалось, выпадает: сообщение уйдёт без этой картинки, но
    уйдёт. Молчание вместо ответа стоит дороже.
    """
    result: list[dict] = []
    for att in attachments:
        url = (att.get("payload") or {}).get("url")
        if not url:
            result.append(att)
            continue
        payload = await upload_media(
            token, _UPLOAD_TYPE_BY_ATTACHMENT.get(att["type"], "file"), url,
        )
        if payload:
            result.append({"type": att["type"], "payload": payload})
        else:
            logger.warning("MAX: вложение не перезалилось, уходит без него | url=%s", url)
    return result


async def send_to_dialog(db: AsyncSession, dialog: Dialog, text: str) -> MaxSentMessage:
    """Отправка в диалог MAX: находит клиента и его бота, шлёт от имени бота.

    На «пользователь остановил бота» помечает диалог `vk_blocked` и пробрасывает
    MaxMessagesForbiddenError — вызывающий не должен ретраить.
    """
    if dialog.vk_blocked:
        raise MaxMessagesForbiddenError(None, None, "dialog is marked vk_blocked")
    client = await db.get(Client, dialog.client_id)
    if not client or not client.vk_user_id or not client.vk_group_id:
        raise ValueError(f"dialog {dialog.id} has no MAX client binding")
    bot = await db.get(VkGroup, client.vk_group_id)
    if not bot or not bot.access_token:
        raise ValueError(f"max bot {client.vk_group_id} not found or has no token")

    cleaned, attachments = build_attachments(text)
    try:
        return await send_message(
            bot.access_token, int(client.vk_user_id), cleaned,
            bot_pk=bot.id, attachments=attachments or None,
        )
    except MaxMessagesForbiddenError as exc:
        dialog.vk_blocked = True
        logger.warning(
            "MAX отказал в отправке (code=%s) — диалог %s помечен vk_blocked",
            exc.code, dialog.id,
        )
        raise
    except MaxApiError as exc:
        # Ссылку на картинку MAX иногда не принимает вовсе («attachment.not.
        # ready» мы уже переждали в клиенте). Пробуем залить файлы сами и
        # повторить — текст без картинки для половины скриптов бесполезен.
        if not attachments:
            logger.error(
                "MAX не принял сообщение | dialog=%s code=%s: %s",
                dialog.id, exc.code, exc.message,
            )
            raise
        logger.warning(
            "MAX не принял вложения по ссылке (%s) — заливаем сами", exc.code,
        )
        uploaded = await _reupload(bot.access_token, attachments)
        return await send_message(
            bot.access_token, int(client.vk_user_id), cleaned,
            bot_pk=bot.id, attachments=uploaded or None,
        )
