"""Приём событий MAX Bot API. Свой адрес на каждого бота: /webhook/max/{id}.

Один адрес на всех, как у ВК, здесь не годится: в событии MAX нет ничего, что
надёжно указывало бы на бота-получателя во всех типах событий (в `bot_started`
и `bot_stopped` сообщения нет вовсе). Адрес мы задаём сами при подписке, и по
нему бот определяется однозначно.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VkGroup
from app.db.session import get_db
from app.max.webhook import schedule_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["max-webhook"])


@router.post("/max/{bot_pk}")
async def max_webhook(
    bot_pk: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    x_max_bot_api_secret: str | None = Header(default=None),
):
    """Приём событий бота. Всегда отвечает мгновенно: обработка уходит в фон,
    MAX ретраит недоставленные события."""
    bot = await db.get(VkGroup, bot_pk)
    if not bot or bot.platform != "max" or not bot.is_active:
        logger.warning("max webhook: неизвестный или выключенный бот | pk=%s", bot_pk)
        raise HTTPException(status_code=404, detail="Unknown bot")

    if bot.secret_key and x_max_bot_api_secret != bot.secret_key:
        logger.warning("max webhook: неверный секрет | pk=%s", bot_pk)
        raise HTTPException(status_code=403, detail="Bad secret")

    schedule_event(bot.id, payload)
    return {"ok": True}
