"""Dialogs CRUD API."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

from app.utils.time import msk_now

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_type_access, get_allowed_type_ids, require_role
from app.db.models import (
    Dialog, DialogPingState, DialogStatusConfig, Message, User,
)
from app.db.session import get_db

router = APIRouter(prefix="/dialogs", tags=["dialogs"])


class PingStateOut(BaseModel):
    id: int
    dialog_id: int
    funnel_type: str
    funnel_reason: str | None = None
    current_step: int
    last_ping_sent_at: datetime | None
    next_ping_due_at: datetime | None
    is_completed: bool
    marketing_tag: str | None

    model_config = {"from_attributes": True}


class DialogOut(BaseModel):
    id: int
    client_id: int
    type_id: int | None
    current_status: str | None
    funnel_stage: str | None = None
    is_test: bool
    ai_paused: bool = False
    vk_blocked: bool = False
    created_at: datetime
    last_message_at: datetime | None
    ping_state: PingStateOut | None = None

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    dialog_id: int
    role: str
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class StatusChangeRequest(BaseModel):
    new_status: str
    reason: str | None = None


class AiPauseRequest(BaseModel):
    paused: bool


@router.get("/", response_model=list[DialogOut])
async def list_dialogs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
    status_filter: str | None = None,
    dialog_type_ids: list[int] = Query(default=[]),
    limit: int = 50,
    offset: int = 0,
):
    q = (
        select(Dialog, DialogStatusConfig.name.label("status_name"))
        .outerjoin(DialogStatusConfig, Dialog.current_status_id == DialogStatusConfig.id)
        .where(Dialog.is_test == False)
    )
    allowed = await get_allowed_type_ids(current_user, db)
    if allowed is not None:
        q = q.where(Dialog.type_id.in_(allowed))
    if status_filter:
        status_result = await db.execute(
            select(DialogStatusConfig.id).where(DialogStatusConfig.name == status_filter)
        )
        status_id = status_result.scalar_one_or_none()
        if status_id is None:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status_filter}")
        q = q.where(Dialog.current_status_id == status_id)
    if dialog_type_ids:
        q = q.where(Dialog.type_id.in_(dialog_type_ids))
    q = q.order_by(Dialog.last_message_at.desc().nullslast()).limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.all()
    return [
        DialogOut(
            id=d.id,
            client_id=d.client_id,
            type_id=d.type_id,
            current_status=status_name,
            is_test=d.is_test,
            created_at=d.created_at,
            last_message_at=d.last_message_at,
        )
        for d, status_name in rows
    ]


@router.get("/{dialog_id}", response_model=DialogOut)
async def get_dialog(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    result = await db.execute(
        select(Dialog, DialogStatusConfig.name.label("status_name"))
        .outerjoin(DialogStatusConfig, Dialog.current_status_id == DialogStatusConfig.id)
        .where(Dialog.id == dialog_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Dialog not found")
    d, status_name = row
    await ensure_type_access(current_user, d.type_id, db)
    ping_result = await db.execute(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog_id)
    )
    ping = ping_result.scalar_one_or_none()
    return DialogOut(
        id=d.id,
        client_id=d.client_id,
        type_id=d.type_id,
        current_status=status_name,
        funnel_stage=d.funnel_stage,
        is_test=d.is_test,
        ai_paused=d.ai_paused,
        vk_blocked=d.vk_blocked,
        created_at=d.created_at,
        last_message_at=d.last_message_at,
        ping_state=PingStateOut.model_validate(ping) if ping else None,
    )


@router.get("/{dialog_id}/messages", response_model=list[MessageOut])
async def get_messages(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)
    result = await db.execute(
        select(Message).where(Message.dialog_id == dialog_id).order_by(Message.created_at)
    )
    return result.scalars().all()


@router.delete("/{dialog_id}/ping-state")
async def delete_ping_state(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Disable current ping funnel; worker will re-detect it on next pass."""
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)
    result = await db.execute(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog_id)
    )
    ping_state = result.scalar_one_or_none()
    if ping_state:
        await db.delete(ping_state)
        await db.commit()
        logger.info("[dialog=%s] ping state deleted by curator — funnel will be re-detected", dialog_id)
    return {"ok": True}


@router.post("/{dialog_id}/status")
async def change_status(
    dialog_id: int,
    body: StatusChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)
    status_result = await db.execute(
        select(DialogStatusConfig).where(
            DialogStatusConfig.name == body.new_status,
            DialogStatusConfig.is_active == True,
        )
    )
    new_status = status_result.scalar_one_or_none()
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Unknown status: {body.new_status}")
    # Статус меняется только локально — внешней системы статусов больше нет.
    dialog.current_status_id = new_status.id
    dialog.updated_at = msk_now()

    if new_status.name == "Ждем предоплату":
        from app.ping.worker import force_ping_funnel
        await force_ping_funnel(db, dialog, "after_payment", msk_now())
    elif new_status.name == "Заказ оформлен":
        ping_result = await db.execute(
            select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
        )
        ping_state = ping_result.scalar_one_or_none()
        if ping_state:
            ping_state.is_completed = True
            logger.info("ping: stopped — order placed | dialog=%s", dialog.id)

    await db.commit()
    return {"ok": True, "new_status": new_status.name}



@router.post("/{dialog_id}/ai-pause")
async def set_ai_pause(
    dialog_id: int,
    body: AiPauseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Пауза/возобновление ИИ в диалоге. Ставится автоматически, когда живой
    оператор отвечает из интерфейса ВК; снимается куратором здесь."""
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)
    dialog.ai_paused = body.paused
    dialog.updated_at = msk_now()
    await db.commit()
    logger.info("[dialog=%s] ai_paused=%s set by user=%s", dialog_id, body.paused, current_user.id)
    return {"ok": True, "ai_paused": dialog.ai_paused}
