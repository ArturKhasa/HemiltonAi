"""Dialog types CRUD API."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_allowed_type_ids, require_role
from app.db.models import DialogType, User
from app.db.session import get_db

router = APIRouter(prefix="/dialog-types", tags=["dialog-types"])


class DialogTypeOut(BaseModel):
    id: int
    name: str
    display_name: str
    is_active: bool
    answer_untagged: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DialogTypeCreateRequest(BaseModel):
    name: str
    display_name: str


class DialogTypeUpdateRequest(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    answer_untagged: bool | None = None


@router.get("/", response_model=list[DialogTypeOut])
async def list_dialog_types(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
    active_only: bool = True,
):
    q = select(DialogType)
    if active_only:
        q = q.where(DialogType.is_active == True)
    allowed = await get_allowed_type_ids(current_user, db)
    if allowed is not None:
        q = q.where(DialogType.id.in_(allowed))
    result = await db.execute(q.order_by(DialogType.id))
    return result.scalars().all()


@router.post("/", response_model=DialogTypeOut, status_code=201)
async def create_dialog_type(
    body: DialogTypeCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    dt = DialogType(name=body.name, display_name=body.display_name)
    db.add(dt)
    await db.flush()
    await db.commit()
    await db.refresh(dt)
    return dt


@router.patch("/{type_id}", response_model=DialogTypeOut)
async def update_dialog_type(
    type_id: int,
    body: DialogTypeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    dt = await db.get(DialogType, type_id)
    if not dt:
        raise HTTPException(status_code=404, detail="Dialog type not found")
    if body.display_name is not None:
        dt.display_name = body.display_name
    if body.is_active is not None:
        dt.is_active = body.is_active
    if body.answer_untagged is not None:
        dt.answer_untagged = body.answer_untagged
    await db.commit()
    await db.refresh(dt)
    return dt
