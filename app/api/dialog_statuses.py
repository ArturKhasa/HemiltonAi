"""CRUD for dialog statuses."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.models import DialogStatusConfig, User
from app.db.session import get_db
from app.utils.time import msk_now

router = APIRouter(prefix="/dialog_statuses", tags=["dialog_statuses"])


class DialogStatusOut(BaseModel):
    id: int
    name: str
    pattern: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DialogStatusCreate(BaseModel):
    name: str
    pattern: str


class DialogStatusUpdate(BaseModel):
    name: str | None = None
    pattern: str | None = None
    is_active: bool | None = None


@router.get("/", response_model=list[DialogStatusOut])
async def list_statuses(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "curator")),
):
    result = await db.execute(
        select(DialogStatusConfig).order_by(DialogStatusConfig.id)
    )
    return result.scalars().all()


@router.post("/", response_model=DialogStatusOut)
async def create_status(
    body: DialogStatusCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    s = DialogStatusConfig(name=body.name, pattern=body.pattern)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@router.patch("/{status_id}", response_model=DialogStatusOut)
async def update_status(
    status_id: int,
    body: DialogStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    s = await db.get(DialogStatusConfig, status_id)
    if not s:
        raise HTTPException(status_code=404, detail="Status not found")
    if body.name is not None:
        s.name = body.name
    if body.pattern is not None:
        s.pattern = body.pattern
    if body.is_active is not None:
        s.is_active = body.is_active
    await db.commit()
    await db.refresh(s)
    return s


@router.delete("/{status_id}")
async def delete_status(
    status_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    s = await db.get(DialogStatusConfig, status_id)
    if not s:
        raise HTTPException(status_code=404, detail="Status not found")
    s.is_active = False
    await db.commit()
    return {"ok": True}
