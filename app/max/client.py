"""Клиент Bot API мессенджера MAX (https://dev.max.ru/docs-api).

Отличия от ВК, из-за которых это отдельный модуль, а не ветка в app.vk.sender:

- токен уходит заголовком `Authorization`, а не параметром запроса;
- ошибка приходит кодом HTTP и телом `{code, message}`, а не полем `error`
  внутри 200 OK;
- вложение прикрепляется внешней ссылкой — перезаливать картинку на свою
  сторону, как в ВК, не нужно;
- лимиты другие: 4000 символов в сообщении и не больше двух сообщений в
  секунду в один диалог.
"""
import asyncio
import logging
from dataclasses import dataclass, field

from app.config import settings
from app.messaging import MessagesForbiddenError
from app.ssl_trust import async_client

logger = logging.getLogger(__name__)

# Лимит MAX на длину одного сообщения; тексты длиннее режутся на части.
MAX_MESSAGE_LEN = 4000
_REQUEST_TIMEOUT = 20.0

# «Не больше двух сообщений в секунду в один диалог» (документация MAX).
# Полсекунды между частями — ровно этот потолок.
_PER_DIALOG_DELAY = 0.5
# Потолок MAX — 30 запросов в секунду на токен. Ограничитель на бота держит нас
# заведомо ниже, не заставляя считать запросы.
_BOT_CONCURRENCY = 4
_semaphores: dict[int, asyncio.Semaphore] = {}

# Типы событий, которые нам нужны. Остальные (правка и удаление сообщений,
# нажатия кнопок, состав чатов) к диалогу продавца отношения не имеют, и
# подписываться на них — лишний трафик в вебхук.
SUBSCRIPTION_UPDATE_TYPES = [
    "message_created",
    "bot_started",
    "bot_stopped",
    "dialog_removed",
]


class MaxApiError(RuntimeError):
    """Ошибка MAX Bot API: HTTP-код и тело `{code, message}`."""

    def __init__(self, status: int | None, code: str | None, message: str):
        super().__init__(f"MAX API error {status}/{code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class MaxMessagesForbiddenError(MaxApiError, MessagesForbiddenError):
    """Писать этому пользователю нельзя: он остановил бота или удалил диалог.

    Общий предок с ВК-версией нужен, чтобы отправка в пингах, приветствиях и
    ответе менеджера из панели ловила одно исключение на обе платформы: смысл
    там один — не ретраить и пометить диалог.
    """


# Признаки того, что писать этому пользователю нельзя: он остановил бота,
# заблокировал его или удалил диалог. Полного списка кодов в документации нет,
# поэтому смотрим на подстроки — а сам код всегда пишем в лог, чтобы список
# можно было уточнить по боевым данным.
_FORBIDDEN_CODE_MARKERS = ("blocked", "denied", "forbidden", "not.found", "stopped")


def _is_forbidden(status: int | None, code: str | None) -> bool:
    if status in (403, 404):
        return True
    lowered = (code or "").lower()
    return any(marker in lowered for marker in _FORBIDDEN_CODE_MARKERS)


def _bot_semaphore(bot_pk: int) -> asyncio.Semaphore:
    sem = _semaphores.get(bot_pk)
    if sem is None:
        sem = _semaphores.setdefault(bot_pk, asyncio.Semaphore(_BOT_CONCURRENCY))
    return sem


@dataclass
class MaxSentMessage:
    """Результат отправки. Форму держим совместимой с app.vk.sender.SentMessage:
    отметки о доставке ставит общий код (app.vk.outgoing.mark_delivered).

    `random_ids` у MAX всегда пуст: собственное эхо в вебхуке к нам не приходит
    (в диалог бота с пользователем больше никто писать не может), и отличать
    свои сообщения от чужих не от чего.
    """
    message_id: str | None = None
    random_ids: list[int] = field(default_factory=list)


async def _request(
    token: str, method: str, path: str, *,
    params: dict | None = None, json: dict | None = None,
) -> dict:
    """Запрос к MAX Bot API. Ошибку разбирает в MaxApiError."""
    async with async_client(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.request(
            method,
            f"{settings.MAX_API_BASE.rstrip('/')}{path}",
            params=params,
            json=json,
            headers={"Authorization": token},
        )
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {}
        code = body.get("code")
        message = body.get("message") or resp.text[:300]
        if _is_forbidden(resp.status_code, code):
            raise MaxMessagesForbiddenError(resp.status_code, code, message)
        raise MaxApiError(resp.status_code, code, message)
    if not resp.content:
        return {}
    return resp.json()


async def get_me(token: str) -> dict:
    """Информация о боте. Заодно единственная проверка, что токен рабочий."""
    return await _request(token, "GET", "/me")


async def list_subscriptions(token: str) -> list[dict]:
    data = await _request(token, "GET", "/subscriptions")
    return data.get("subscriptions") or []


async def get_messages(token: str, chat_id: int, count: int = 10) -> list[dict]:
    """Последние сообщения диалога или группового чата MAX.

    Нужны только как страховка при первом сообщении клиента: если оператор
    успел ответить от имени бота вне панели, прежде чем наш вебхук увидел это
    исходящее, AI не должен вступать в уже ручной диалог.
    """
    data = await _request(
        token, "GET", "/messages", params={"chat_id": chat_id, "count": count},
    )
    return data.get("messages") or []


async def subscribe(token: str, url: str, secret: str) -> dict:
    """Подписать бота на вебхук. MAX принимает только https-адрес."""
    return await _request(
        token, "POST", "/subscriptions",
        json={"url": url, "update_types": SUBSCRIPTION_UPDATE_TYPES, "secret": secret},
    )


async def unsubscribe(token: str, url: str) -> dict:
    return await _request(token, "DELETE", "/subscriptions", params={"url": url})


async def send_message(
    token: str,
    user_id: int,
    text: str,
    bot_pk: int | None = None,
    attachments: list[dict] | None = None,
) -> MaxSentMessage:
    """Отправка текста пользователю от имени бота.

    Длинный текст уходит несколькими сообщениями; вложения — вместе с
    ПОСЛЕДНИМ куском, как и в ВК: фраза, к которой они относятся, обычно им и
    заканчивается. Возвращает mid последней отправленной части.
    """
    from app.vk.sender import split_text

    chunks = split_text(text, MAX_MESSAGE_LEN)
    if not chunks and not attachments:
        return MaxSentMessage()
    if not chunks:
        chunks = [""]

    sent = MaxSentMessage()
    async with _bot_semaphore(bot_pk or 0):
        for i, chunk in enumerate(chunks):
            if i:
                await asyncio.sleep(_PER_DIALOG_DELAY)
            body: dict = {"text": chunk}
            if attachments and i == len(chunks) - 1:
                body["attachments"] = attachments
            data = await _send_one(token, user_id, body)
            mid = ((data.get("message") or {}).get("body") or {}).get("mid")
            if mid:
                sent.message_id = str(mid)
    return sent


# Сколько раз ждём, пока MAX доготовит вложение. Картинку по внешней ссылке он
# качает к себе уже после ответа на запрос, и первая же отправка отвечает
# `attachment.not.ready` — это не отказ, а «ещё не готово».
_ATTACHMENT_RETRIES = 4
_ATTACHMENT_RETRY_DELAY = 1.5


async def _send_one(token: str, user_id: int, body: dict) -> dict:
    for attempt in range(_ATTACHMENT_RETRIES):
        try:
            return await _request(
                token, "POST", "/messages", params={"user_id": user_id}, json=body,
            )
        except MaxApiError as exc:
            not_ready = "not.ready" in (exc.code or "").lower()
            if not not_ready or attempt == _ATTACHMENT_RETRIES - 1:
                raise
            logger.info(
                "MAX ещё готовит вложение, ждём | user_id=%s | попытка %d",
                user_id, attempt + 1,
            )
            await asyncio.sleep(_ATTACHMENT_RETRY_DELAY)
    raise MaxApiError(None, None, "unreachable")


async def upload_media(token: str, upload_type: str, url: str) -> dict | None:
    """Залить файл по ссылке в MAX и вернуть payload вложения.

    Запасной путь для случая, когда MAX не принимает внешнюю ссылку напрямую:
    берём файл сами и отдаём в их хранилище. Возвращает готовый payload для
    `attachments` либо None, если залить не удалось (тогда сообщение уйдёт без
    картинки — это лучше, чем не уйти совсем).
    """
    try:
        endpoint = await _request(
            token, "POST", "/uploads", params={"type": upload_type},
        )
        upload_url = endpoint.get("url")
        if not upload_url:
            return None
        async with async_client(timeout=60.0, follow_redirects=True) as client:
            src = await client.get(url)
            src.raise_for_status()
            name = (url.split("?", 1)[0].rsplit("/", 1)[-1]) or "file"
            uploaded = await client.post(
                upload_url,
                files={"data": (name, src.content, src.headers.get("content-type"))},
            )
            uploaded.raise_for_status()
            result = uploaded.json() if uploaded.content else {}
    except Exception as exc:
        logger.warning("MAX upload не удался | url=%s: %s", url, exc)
        return None

    # Изображения возвращаются как {"photos": {key: {"token": …}}}, остальные
    # типы — плоским {"token": …} (см. PhotoTokens / MediaAttachmentPayload).
    if result.get("photos"):
        return {"photos": result["photos"]}
    if result.get("token"):
        return {"token": result["token"]}
    if endpoint.get("token"):
        return {"token": endpoint["token"]}
    return None
