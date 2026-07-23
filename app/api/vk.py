"""VK Callback API endpoint — один на все группы, группа определяется по group_id."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VkGroup
from app.db.session import get_db
from app.vk.webhook import schedule_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["vk-webhook"])


@router.post("/vk")
async def vk_webhook(payload: dict, db: AsyncSession = Depends(get_db)):
    """Приём событий Callback API. Всегда отвечает за < 5 сек: обработка
    message_new/message_reply уходит в фон, ВК ретраит недоставленные события."""
    group_id = payload.get("group_id")
    if not group_id:
        raise HTTPException(status_code=422, detail="group_id missing")

    group = await db.scalar(
        select(VkGroup).where(VkGroup.group_id == int(group_id), VkGroup.is_active == True)
    )
    if not group:
        logger.warning("vk webhook: unknown or inactive group_id=%s", group_id)
        raise HTTPException(status_code=404, detail="Unknown group")

    event_type = payload.get("type")
    if event_type == "confirmation":
        return PlainTextResponse(group.confirmation_code)

    if group.secret_key and payload.get("secret") != group.secret_key:
        logger.warning("vk webhook: bad secret | group_id=%s", group_id)
        raise HTTPException(status_code=403, detail="Bad secret")

    if event_type in ("message_new", "message_reply"):
        schedule_event(group.id, payload)

    return PlainTextResponse("ok")
