"""CRUD подключённых сообществ ВК (только admin). Токен наружу не отдаётся — маска."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.models import User, VkGroup
from app.db.session import get_db

router = APIRouter(prefix="/vk-groups", tags=["vk-groups"])


def _mask_token(token: str | None) -> str:
    if not token:
        return ""
    return f"…{token[-4:]}" if len(token) > 4 else "…"


class VkGroupOut(BaseModel):
    id: int
    group_id: int
    name: str
    access_token_mask: str
    confirmation_code: str
    has_secret: bool
    dialog_type_id: int | None
    is_active: bool
    created_at: datetime


class VkGroupCreateRequest(BaseModel):
    group_id: int
    name: str
    access_token: str
    confirmation_code: str
    secret_key: str | None = None
    dialog_type_id: int | None = None


class VkGroupUpdateRequest(BaseModel):
    name: str | None = None
    access_token: str | None = None  # пустое/None = не менять
    confirmation_code: str | None = None
    secret_key: str | None = None
    dialog_type_id: int | None = None
    is_active: bool | None = None


def _to_out(g: VkGroup) -> VkGroupOut:
    return VkGroupOut(
        id=g.id,
        group_id=g.group_id,
        name=g.name,
        access_token_mask=_mask_token(g.access_token),
        confirmation_code=g.confirmation_code,
        has_secret=bool(g.secret_key),
        dialog_type_id=g.dialog_type_id,
        is_active=bool(g.is_active),
        created_at=g.created_at,
    )


@router.get("/", response_model=list[VkGroupOut])
async def list_vk_groups(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    result = await db.execute(select(VkGroup).order_by(VkGroup.id))
    return [_to_out(g) for g in result.scalars().all()]


@router.post("/", response_model=VkGroupOut, status_code=201)
async def create_vk_group(
    body: VkGroupCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    existing = await db.scalar(select(VkGroup).where(VkGroup.group_id == body.group_id))
    if existing:
        raise HTTPException(status_code=409, detail="Group with this group_id already exists")
    group = VkGroup(
        group_id=body.group_id,
        name=body.name,
        access_token=body.access_token,
        confirmation_code=body.confirmation_code,
        secret_key=body.secret_key or None,
        dialog_type_id=body.dialog_type_id,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return _to_out(group)


@router.patch("/{group_pk}", response_model=VkGroupOut)
async def update_vk_group(
    group_pk: int,
    body: VkGroupUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    group = await db.get(VkGroup, group_pk)
    if not group:
        raise HTTPException(status_code=404, detail="VK group not found")
    updates = body.model_dump(exclude_unset=True)
    # Пустой access_token в PATCH означает «оставить текущий» (в UI токен показан маской).
    if not updates.get("access_token"):
        updates.pop("access_token", None)
    for k, v in updates.items():
        setattr(group, k, v)
    await db.commit()
    await db.refresh(group)
    return _to_out(group)


@router.delete("/{group_pk}", status_code=204)
async def delete_vk_group(
    group_pk: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    group = await db.get(VkGroup, group_pk)
    if not group:
        raise HTTPException(status_code=404, detail="VK group not found")
    await db.delete(group)
    await db.commit()
