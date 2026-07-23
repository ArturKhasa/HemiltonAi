"""Message feedback CRUD API."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.feedback import invalidate_feedback_cache
from app.auth.dependencies import require_role
from app.db.models import Dialog, Message, MessageFeedback, MessageRole, User
from app.db.session import get_db

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackCreateRequest(BaseModel):
    rule_text: str

    @field_validator("rule_text")
    @classmethod
    def min_length(cls, v: str) -> str:
        if len(v.strip()) < 30:
            raise ValueError("rule_text must be at least 30 characters")
        return v


class FeedbackUpdateRequest(BaseModel):
    rule_text: str | None = None
    is_active: bool | None = None

    @field_validator("rule_text")
    @classmethod
    def min_length(cls, v: str | None) -> str | None:
        if v is not None and len(v.strip()) < 30:
            raise ValueError("rule_text must be at least 30 characters")
        return v


class FeedbackOut(BaseModel):
    id: int
    message_id: int
    type_id: int | None
    rule_text: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.post("/messages/{message_id}", response_model=FeedbackOut, status_code=201)
async def create_feedback(
    message_id: int,
    body: FeedbackCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    message = await db.get(Message, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.role != MessageRole.ai:
        raise HTTPException(status_code=400, detail="Feedback only allowed on AI messages")

    existing = await db.execute(
        select(MessageFeedback).where(MessageFeedback.message_id == message_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Feedback already exists, use PATCH to update")

    dialog = await db.get(Dialog, message.dialog_id)
    type_id = dialog.type_id if dialog else None
    is_ping = bool((message.msg_metadata or {}).get("ping", False))

    feedback = MessageFeedback(
        message_id=message_id,
        type_id=type_id,
        user_id=current_user.id,
        rule_text=body.rule_text.strip(),
        is_ping=is_ping,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    invalidate_feedback_cache(type_id, is_ping)
    return feedback


@router.patch("/{feedback_id}", response_model=FeedbackOut)
async def update_feedback(
    feedback_id: int,
    body: FeedbackUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "curator")),
):
    feedback = await db.get(MessageFeedback, feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    if body.rule_text is not None:
        feedback.rule_text = body.rule_text.strip()
    if body.is_active is not None:
        feedback.is_active = body.is_active

    await db.commit()
    await db.refresh(feedback)

    invalidate_feedback_cache(feedback.type_id, feedback.is_ping)
    return feedback


@router.delete("/{feedback_id}", status_code=204)
async def delete_feedback(
    feedback_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "curator")),
):
    feedback = await db.get(MessageFeedback, feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    type_id = feedback.type_id
    await db.delete(feedback)
    await db.commit()
    invalidate_feedback_cache(type_id, feedback.is_ping)


@router.get("/", response_model=list[FeedbackOut])
async def list_feedbacks(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "curator")),
    type_id: int | None = None,
    include_inactive: bool = False,
):
    q = select(MessageFeedback)
    if type_id is not None:
        q = q.where(MessageFeedback.type_id == type_id)
    if not include_inactive:
        q = q.where(MessageFeedback.is_active == True)
    q = q.order_by(MessageFeedback.created_at.desc())
    result = await db.execute(q)
    return result.scalars().all()
