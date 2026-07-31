"""Ref-метки рекламных ссылок — CRUD для админки."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.models import User
from app.db.session import get_db
from app.sales.ref_tags import RefTagService

router = APIRouter(prefix="/ref-tags", tags=["ref-tags"])


class RefTagOut(BaseModel):
    id: int
    type_id: int | None
    tag: str
    is_active: bool
    greeting_script_id: int | None
    note: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class RefTagCreateRequest(BaseModel):
    tag: str
    type_id: int | None = None
    is_active: bool = True
    greeting_script_id: int | None = None
    note: str | None = None


class RefTagUpdateRequest(BaseModel):
    tag: str | None = None
    is_active: bool | None = None
    greeting_script_id: int | None = None
    note: str | None = None


@router.get("/", response_model=list[RefTagOut])
async def list_ref_tags(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
    type_id: int | None = None,
):
    return await RefTagService(db).list_all(type_id=type_id)


@router.post("/", response_model=RefTagOut, status_code=201)
async def create_ref_tag(
    body: RefTagCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    tag = (body.tag or "").strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Метка не может быть пустой")
    svc = RefTagService(db)
    if await svc.get(tag, body.type_id) is not None:
        raise HTTPException(status_code=400, detail="Такая метка уже есть")
    row = await svc.create(
        tag, type_id=body.type_id, is_active=body.is_active,
        greeting_script_id=body.greeting_script_id or None,
        note=(body.note or "").strip() or None,
    )
    await db.commit()
    await db.refresh(row)
    return row


@router.patch("/{ref_tag_id}", response_model=RefTagOut)
async def update_ref_tag(
    ref_tag_id: int,
    body: RefTagUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    updates = body.model_dump(exclude_none=True)
    if "tag" in updates:
        updates["tag"] = updates["tag"].strip()
        if not updates["tag"]:
            raise HTTPException(status_code=400, detail="Метка не может быть пустой")
    # exclude_none выше съедает явный null, поэтому «приветствия нет» приходит нулём.
    if updates.get("greeting_script_id") == 0:
        updates["greeting_script_id"] = None
    if "note" in updates:
        updates["note"] = updates["note"].strip() or None
    row = await RefTagService(db).update(ref_tag_id, **updates)
    if not row:
        raise HTTPException(status_code=404, detail="Метка не найдена")
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{ref_tag_id}", status_code=204)
async def delete_ref_tag(
    ref_tag_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    if not await RefTagService(db).delete(ref_tag_id):
        raise HTTPException(status_code=404, detail="Метка не найдена")
    await db.commit()
