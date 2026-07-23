"""Отправка сообщений через VK API (messages.send).

HTTP 200 от ВК не значит успех — ошибка приходит в теле ответа (`error`),
поэтому тело проверяется всегда. Коды 900/901/902 (клиент запретил сообщения
от сообщества) терминальны: диалог помечается vk_blocked, ретраев нет.
"""
import asyncio
import logging
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Client, Dialog, VkGroup

logger = logging.getLogger(__name__)

VK_API_BASE = "https://api.vk.com/method"
# Лимит ВК на длину одного сообщения; более длинные тексты режутся на части.
MAX_MESSAGE_LEN = 4096
_REQUEST_TIMEOUT = 15.0

# 900 — клиент в ЧС сообщества; 901/902 — сообщения от сообщества запрещены настройками.
_FORBIDDEN_CODES = frozenset({900, 901, 902})

# Простой ограничитель параллелизма на группу (у ВК ~20 rps на токен).
_GROUP_CONCURRENCY = 4
_semaphores: dict[int, asyncio.Semaphore] = {}


class VkApiError(RuntimeError):
    """Ошибка в теле ответа VK API."""

    def __init__(self, code: int | None, message: str):
        super().__init__(f"VK API error {code}: {message}")
        self.code = code
        self.message = message


class VkMessagesForbiddenError(VkApiError):
    """Клиент запретил сообщения от сообщества (900/901/902) — не ретраить."""


def _group_semaphore(group_id: int) -> asyncio.Semaphore:
    sem = _semaphores.get(group_id)
    if sem is None:
        sem = _semaphores.setdefault(group_id, asyncio.Semaphore(_GROUP_CONCURRENCY))
    return sem


def check_vk_response(data: dict):
    """Достаёт `response` из тела ответа ВК; `error` в теле → исключение."""
    if "error" in data:
        err = data["error"] or {}
        code = err.get("error_code")
        msg = err.get("error_msg") or str(err)
        if code in _FORBIDDEN_CODES:
            raise VkMessagesForbiddenError(code, msg)
        raise VkApiError(code, msg)
    return data.get("response")


async def vk_api_call(access_token: str, method: str, params: dict):
    """POST на VK API. Возвращает содержимое `response`."""
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.post(
            f"{VK_API_BASE}/{method}",
            data={**params, "access_token": access_token, "v": settings.VK_API_VERSION},
        )
    resp.raise_for_status()
    return check_vk_response(resp.json())


def split_text(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Режет текст на части ≤ limit, предпочитая границы абзацев/строк/слов."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while len(text) > limit:
        cut = -1
        for sep in ("\n\n", "\n", " "):
            cut = text.rfind(sep, 0, limit + 1)
            if cut > 0:
                break
        if cut <= 0:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def make_random_id() -> int:
    """random_id обязателен для messages.send — ВК дедуплицирует по нему повторы."""
    return uuid.uuid4().int & 0x7FFF_FFFF


async def send_message(
    access_token: str,
    peer_id: int,
    text: str,
    vk_group_id: int | None = None,
) -> int | None:
    """Отправка текста в ЛС пользователю от имени сообщества.

    Длинный текст уходит несколькими сообщениями. Возвращает VK message id
    последней отправленной части (None, если текст пуст).
    """
    chunks = split_text(text)
    if not chunks:
        return None
    sem = _group_semaphore(vk_group_id or 0)
    last_id: int | None = None
    async with sem:
        for chunk in chunks:
            last_id = await vk_api_call(
                access_token,
                "messages.send",
                {"peer_id": peer_id, "message": chunk, "random_id": make_random_id()},
            )
    return last_id


async def send_to_dialog(db: AsyncSession, dialog: Dialog, text: str) -> int | None:
    """Отправка в диалог: находит клиента и его группу, шлёт от её имени.

    На 900/901/902 помечает диалог vk_blocked и пробрасывает
    VkMessagesForbiddenError — вызывающий не должен ретраить.
    Возвращает VK message id последней части (для external_message_id).
    """
    if dialog.vk_blocked:
        raise VkMessagesForbiddenError(None, "dialog is marked vk_blocked")
    client = await db.get(Client, dialog.client_id)
    if not client or not client.vk_user_id or not client.vk_group_id:
        raise ValueError(f"dialog {dialog.id} has no VK client binding")
    group = await db.get(VkGroup, client.vk_group_id)
    if not group or not group.access_token:
        raise ValueError(f"vk group {client.vk_group_id} not found or has no token")
    try:
        return await send_message(
            group.access_token, int(client.vk_user_id), text, vk_group_id=group.id,
        )
    except VkMessagesForbiddenError as e:
        dialog.vk_blocked = True
        logger.warning(
            "vk send forbidden (code=%s) — dialog %s marked vk_blocked", e.code, dialog.id,
        )
        raise
    except VkApiError as e:
        logger.error("vk send failed | dialog=%s code=%s: %s", dialog.id, e.code, e.message)
        raise
