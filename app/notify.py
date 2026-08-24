"""Уведомление менеджеров о диалоге, который требует человека.

Система умела ставить статус «Нужен куратор» и снимать ИИ с диалога, но никуда
об этом не сообщала: в коде не было ни одного уведомления. Менеджер узнавал об
эскалации, только если сам открывал панель. ОП, 10 августа, 14:12: «Тут надо
бросать диалог, должен подключаться менеджер и пинговать клиента индивидуально.
Не общими, как бот».

Канал — телеграм-бот. Пока токен и чат не заданы в настройках, функция молча
ничего не делает: развёртывание от этого не ломается, а включение сводится к
двум переменным окружения.
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
# Обрезаем цитату последнего сообщения: уведомление должно читаться с телефона.
_QUOTE_LIMIT = 300


def notifications_configured() -> bool:
    return bool(
        (getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "").strip()
        and (getattr(settings, "TELEGRAM_ALERT_CHAT_ID", "") or "").strip()
    )


def _dialog_url(dialog_id: int) -> str:
    base = (getattr(settings, "PANEL_PUBLIC_URL", "") or "").strip().rstrip("/")
    return f"{base}/chat?dialog={dialog_id}" if base else f"диалог #{dialog_id}"


async def notify_curator(
    dialog_id: int,
    reason: str,
    last_message: str | None = None,
    vk_user_id: int | None = None,
    platform: str = "vk",
) -> None:
    """Сообщить менеджерам, что диалог ждёт человека. Ошибки не пробрасываем:
    неотправленное уведомление не должно ронять ответ клиенту."""
    if not notifications_configured():
        logger.info(
            "уведомление не отправлено — телеграм не настроен | dialog=%s | %s",
            dialog_id, reason,
        )
        return

    lines = [f"🔔 Диалог ждёт менеджера: {reason}", _dialog_url(dialog_id)]
    if vk_user_id:
        # У MAX публичной ссылки на профиль по числовому ID нет — показываем сам
        # ID: по нему клиента видно в панели, а ссылка вида vk.com/id… для
        # клиента из MAX вела бы на чужой профиль.
        lines.append(
            f"Клиент: vk.com/id{vk_user_id}" if platform == "vk"
            else f"Клиент: MAX id{vk_user_id}"
        )
    if last_message:
        lines.append(f"Последнее сообщение: «{last_message[:_QUOTE_LIMIT]}»")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": settings.TELEGRAM_ALERT_CHAT_ID,
                    "text": "\n".join(lines),
                    "disable_web_page_preview": True,
                },
            )
        resp.raise_for_status()
        logger.info("уведомление отправлено | dialog=%s | %s", dialog_id, reason)
    except Exception as exc:
        logger.warning("уведомление не ушло | dialog=%s: %s", dialog_id, exc)
