"""Отправка сообщений через VK API (messages.send).

HTTP 200 от ВК не значит успех — ошибка приходит в теле ответа (`error`),
поэтому тело проверяется всегда. Коды 900/901/902 (клиент запретил сообщения
от сообщества) терминальны: диалог помечается vk_blocked, ретраев нет.
"""
import asyncio
import logging
import re
import uuid
from collections import deque
from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Client, Dialog, VkGroup

logger = logging.getLogger(__name__)

VK_API_BASE = "https://api.vk.com/method"
# Лимит ВК на длину одного сообщения; более длинные тексты режутся на части.
MAX_MESSAGE_LEN = 4096
_REQUEST_TIMEOUT = 15.0
# VK messages.send принимает максимум 10 attachment-объектов на сообщение.
_MAX_ATTACHMENTS = 10

# Готовые фразы (импортированные из старой CRM/бот-платформы) хранят вложения
# прямо в тексте, тремя формами:
#
# 1) "[video-<owner>_<id>]" / "[clip-<owner>_<id>]" — ВИДЕО чужого сообщества.
#    Прикрепляется как есть: проверено отправкой в ВК, оба ролика из выгрузки ОП
#    (сообщества 228420497 и 44440184) дошли вложением, messages.getById
#    показывает их в attachments.
# 2) "[photo-https://...]" — скачиваемая ссылка. Перезаливается на СВОЁ
#    сообщество через app.vk.photo_upload.resolve_attachment (с кэшем).
# 3) "[photo-<owner>_<id>]" / "[audio_message<id>_<id>]" — чужой media-id без
#    ссылки. Тут ВК уже разборчив: фото одного сообщества прикрепилось, другого
#    и голосовое — молча выброшены. Полагаться нельзя, вырезаем как мусор; для
#    фото рабочий путь — форма 2.
_DEAD_ATTACHMENT_TOKEN_RE = re.compile(r"\[(?:photo|audio_message)-?\d+_\d+\]")
# Токен, в котором ни ссылки, ни id — модель придумала его сама. Пробел внутри
# разрешён: именно так и выглядит выдумка («[photo-фиолетовый свитшот]»).
_JUNK_ATTACHMENT_TOKEN_RE = re.compile(r"\[(?:photo|video|clip|audio_message)-?[^\]\n]*\]")
_PHOTO_URL_TOKEN_RE = re.compile(r"\[photo-(https?://[^\]]+)\]")
_VIDEO_URL_TOKEN_RE = re.compile(r"\[video-(https?://[^\]]+)\]")
# "[video-1_2]" и "[clip-1_2]" — минус владельца-сообщества внутри числа.
_VIDEO_ID_TOKEN_RE = re.compile(r"\[(?:video|clip)(-?\d+_\d+)\]")
# Ссылка на ролик: https://vkvideo.ru/video-44440184_456240651 и clip-версия.
_VIDEO_URL_IDS_RE = re.compile(r"(?:video|clip)(-?\d+_\d+)")


async def extract_and_resolve_attachments(
    db: AsyncSession, group: VkGroup, text: str,
) -> tuple[str, str | None]:
    """Разбирает вложения в тексте фразы перед отправкой в VK:
    - "[photo-<url>]" — скачивает и перезаливает на СВОЁ сообщество (с кэшем),
      добавляет в attachment; если перезалить не удалось — просто вырезается.
    - "[video-<url>]" — полноценная перезаливка видео не реализована, ссылка
      остаётся голым текстом (VK сам разворачивает превью).
    - "[photo/video/audio_message-<id>_<id>]" — мёртвый чужой VK ID, вырезается.

    Возвращает (текст без токенов, attachment-строка для messages.send через
    запятую, или None если вложений нет).
    """
    from app.vk.photo_upload import resolve_attachment  # local: avoids import cycle (photo_upload imports vk_api_call from here)

    attachments: list[str] = []
    for m in _PHOTO_URL_TOKEN_RE.finditer(text or ""):
        att = await resolve_attachment(db, group, m.group(1))
        if att:
            attachments.append(att)
        else:
            # Раньше несработавший перезалив был виден только в логе самого
            # resolve_attachment: токен молча вырезался, и сообщение уходило без
            # картинки, о которой мы даже не знали, что её нет.
            logger.warning("вложение не перезалилось, уходит без картинки | url=%s", m.group(1))
    cleaned = _PHOTO_URL_TOKEN_RE.sub("", text or "")

    # Видео идёт вложением по id — и из голого токена, и из ссылки на vkvideo.
    for m in _VIDEO_ID_TOKEN_RE.finditer(cleaned):
        attachments.append(f"video{m.group(1)}")
    cleaned = _VIDEO_ID_TOKEN_RE.sub("", cleaned)

    # Ссылка, из которой id не вытащить (не vkvideo), вложением стать не может —
    # оставляем её текстом, но отдельной строкой в конце: на месте токена она
    # прилипала к вопросу и читалась как опечатка.
    leftover_urls: list[str] = []
    for m in _VIDEO_URL_TOKEN_RE.finditer(cleaned):
        url = m.group(1)
        ids = _VIDEO_URL_IDS_RE.search(url)
        if ids:
            attachments.append(f"video{ids.group(1)}")
        else:
            leftover_urls.append(url)
    cleaned = _VIDEO_URL_TOKEN_RE.sub("", cleaned)

    cleaned = _DEAD_ATTACHMENT_TOKEN_RE.sub("", cleaned)
    # Выдуманный токен: «Фиолетовый свитшот выглядит так: [photo-фиолетовый
    # свитшот]» ушло клиенту как есть (прогон 1369). Инструмент ответил «Фото не
    # найдено» — такого цвета в матрице нет, — а модель всё равно сослалась на
    # картинку. Ни ссылки, ни id внутри нет, прикреплять нечего — вырезаем.
    junk = _JUNK_ATTACHMENT_TOKEN_RE.findall(cleaned)
    if junk:
        logger.warning("выдуманные токены вложений вырезаны | tokens=%s", junk[:3])
        cleaned = _JUNK_ATTACHMENT_TOKEN_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    for url in leftover_urls:
        if url not in cleaned:
            cleaned = f"{cleaned}\n\n{url}" if cleaned else url

    if len(attachments) > _MAX_ATTACHMENTS:
        logger.warning("extract_and_resolve_attachments: %d attachments, capping at %d", len(attachments), _MAX_ATTACHMENTS)
        attachments = attachments[:_MAX_ATTACHMENTS]
    return cleaned, (",".join(attachments) if attachments else None)

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


# random_id всех наших отправок за последнее время, В ПАМЯТИ процесса.
#
# Одной записи в БД мало: ВК присылает эхо нашей же отправки через одну-две
# секунды, а метаданные к этому моменту ещё не закоммичены — ход коммитится
# целиком, уже после паузы между репликами связки. Эхо не опознавалось, летело
# в базу как сообщение живого оператора, забирало себе VK id — и наш коммит
# падал на уникальном индексе (dialog_id, external_message_id) и откатывался
# вместе с отметками о доставке. Диалог при этом вставал на паузу сам от себя:
# 11 августа так замолчали 92 диалога.
#
# Здесь запись появляется ДО обращения к ВК, поэтому гонки нет вовсе.
_OUR_RANDOM_IDS: deque[int] = deque(maxlen=5000)
_OUR_RANDOM_IDS_SET: set[int] = set()


def remember_random_id(random_id: int) -> None:
    """Запомнить, что этим random_id отправляли мы."""
    if len(_OUR_RANDOM_IDS) == _OUR_RANDOM_IDS.maxlen:
        _OUR_RANDOM_IDS_SET.discard(_OUR_RANDOM_IDS[0])
    _OUR_RANDOM_IDS.append(random_id)
    _OUR_RANDOM_IDS_SET.add(random_id)


def is_own_random_id(random_id: int) -> bool:
    """Отправляли ли мы сами сообщение с таким random_id."""
    return bool(random_id) and random_id in _OUR_RANDOM_IDS_SET


@dataclass
class SentMessage:
    """Результат отправки: VK id последней части и все random_id, которыми мы
    отправляли.

    random_id нужны на входе: ВК присылает нам message_reply и о наших
    отправках тоже, и отличить своё эхо от сообщения живого менеджера можно
    только по нему (см. app.vk.webhook.handle_message_reply)."""
    message_id: int | None = None
    random_ids: list[int] = field(default_factory=list)


async def send_message(
    access_token: str,
    peer_id: int,
    text: str,
    vk_group_id: int | None = None,
    attachment: str | None = None,
) -> SentMessage:
    """Отправка текста в ЛС пользователю от имени сообщества.

    Длинный текст уходит несколькими сообщениями. attachment (если задан) уходит
    вместе с ПОСЛЕДНИМ чанком — обычно фразы, на которые ссылаются вложения,
    заканчиваются ими. Возвращает VK message id последней отправленной части и
    список random_id всех частей (message_id=None, если отправлять было нечего).
    """
    chunks = split_text(text)
    if not chunks and not attachment:
        return SentMessage()
    if not chunks:
        chunks = [""]
    sem = _group_semaphore(vk_group_id or 0)
    sent = SentMessage()
    async with sem:
        for i, chunk in enumerate(chunks):
            random_id = make_random_id()
            params = {"peer_id": peer_id, "message": chunk, "random_id": random_id}
            if attachment and i == len(chunks) - 1:
                params["attachment"] = attachment
            # random_id запоминаем ДО вызова: ВК успевает прислать нам эхо
            # раньше, чем вернёт ответ, и к этому моменту id уже должен быть наш.
            remember_random_id(random_id)
            sent.random_ids.append(random_id)
            sent.message_id = await vk_api_call(access_token, "messages.send", params)
    return sent


async def fetch_user_name(access_token: str, vk_user_id: int) -> tuple[str | None, str | None]:
    """Имя и фамилия клиента из его профиля ВК.

    Раньше мы его не запрашивали вовсе: у всех 74 боевых клиентов в базе
    `clients.name` пуст. Обращаться было нечем, и модель звала клиента
    единственным именем, которое видела, — надписью, заказанной на изделие
    («Михаил» из надписи «Хананов Михаил» клиентке Анастасии, диалог 163).

    Фамилия нужна списку лидов — там вместо неё стоял числовой VK ID. В самом
    диалоге фамилия не используется: обращаться по ней нельзя.

    Ошибка ВК здесь не должна ронять ответ клиенту: без имени просто перейдём
    на «Вы».
    """
    try:
        rows = await vk_api_call(
            access_token, "users.get",
            {"user_ids": str(vk_user_id), "fields": "first_name,last_name"},
        )
    except Exception as exc:
        logger.warning("users.get failed | vk_user_id=%s: %s", vk_user_id, exc)
        return None, None
    if not rows:
        return None, None
    first = (rows[0].get("first_name") or "").strip()
    last = (rows[0].get("last_name") or "").strip()
    return first or None, last or None


async def verify_attachments_delivered(
    db: AsyncSession, group: VkGroup, message_id: int | None, attachment: str,
) -> bool:
    """Дошли ли вложения до клиента на самом деле.

    ВК принимает `attachment` с мёртвым объектом БЕЗ ошибки и просто не кладёт
    его в сообщение: отправка успешна, в базе `delivered: true`, картинок у
    клиента нет. Так десять дней уходили цена без фото и оформление без отзывов
    (см. photo_upload.forget_attachments).

    Поэтому спрашиваем у ВК, что он реально отправил. Недостача — выкидываем эти
    объекты из кэша: следующая отправка перезальёт их с исходных ссылок и
    картинки вернутся сами.
    """
    from app.vk.photo_upload import forget_attachments

    expected = [a for a in attachment.split(",") if a]
    if not message_id or not expected:
        return True
    try:
        data = await vk_api_call(
            group.access_token, "messages.getById", {"message_ids": message_id},
        )
        items = (data or {}).get("items") or []
        delivered = len((items[0].get("attachments") or [])) if items else 0
    except Exception as exc:
        # Проверка — не повод ронять отправку: сообщение клиент уже получил.
        logger.warning("не удалось проверить вложения | message_id=%s: %s", message_id, exc)
        return True
    if delivered >= len(expected):
        return True
    dropped = await forget_attachments(db, group.id, expected)
    logger.error(
        "ВК выбросил вложения: ожидали %d, доехало %d | message_id=%s | из кэша убрано %d "
        "— следующая отправка перезальёт",
        len(expected), delivered, message_id, dropped,
    )
    return False


async def send_to_dialog(db: AsyncSession, dialog: Dialog, text: str) -> SentMessage:
    """Отправка в диалог: находит клиента и его группу, шлёт от её имени.

    Вложения из фраз ("[photo-url]" и т.п., см. extract_and_resolve_attachments)
    перезаливаются/вырезаются и уходят как VK attachment, а не сырой текст.

    На 900/901/902 помечает диалог vk_blocked и пробрасывает
    VkMessagesForbiddenError — вызывающий не должен ретраить.
    Возвращает SentMessage: VK id последней части (для external_message_id) и
    random_id всех частей (для распознавания собственного эха).
    """
    if dialog.vk_blocked:
        raise VkMessagesForbiddenError(None, "dialog is marked vk_blocked")
    client = await db.get(Client, dialog.client_id)
    if not client or not client.vk_user_id or not client.vk_group_id:
        raise ValueError(f"dialog {dialog.id} has no VK client binding")
    group = await db.get(VkGroup, client.vk_group_id)
    if not group or not group.access_token:
        raise ValueError(f"vk group {client.vk_group_id} not found or has no token")
    text, attachment = await extract_and_resolve_attachments(db, group, text)
    try:
        sent = await send_message(
            group.access_token, int(client.vk_user_id), text,
            vk_group_id=group.id, attachment=attachment,
        )
        if attachment:
            await verify_attachments_delivered(db, group, sent.message_id, attachment)
        return sent
    except VkMessagesForbiddenError as e:
        dialog.vk_blocked = True
        logger.warning(
            "vk send forbidden (code=%s) — dialog %s marked vk_blocked", e.code, dialog.id,
        )
        raise
    except VkApiError as e:
        logger.error("vk send failed | dialog=%s code=%s: %s", dialog.id, e.code, e.message)
        raise
