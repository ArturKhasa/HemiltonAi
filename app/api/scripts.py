"""Scripts CRUD API."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.models import User
from app.db.session import get_db
from app.storage.rehost import rehost_external_photos
from app.sales.scripts import ScriptService

router = APIRouter(prefix="/scripts", tags=["scripts"])


class ScriptOut(BaseModel):
    id: int
    type_id: int | None
    condition: str
    phrase_text: str
    marketing_tag: str | None
    funnel_stage: str | None
    follow_up_script_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScriptCreateRequest(BaseModel):
    condition: str
    phrase_text: str
    type_id: int | None = None
    marketing_tag: str | None = None
    funnel_stage: str | None = None
    follow_up_script_id: int | None = None


class ScriptUpdateRequest(BaseModel):
    condition: str | None = None
    phrase_text: str | None = None
    type_id: int | None = None
    marketing_tag: str | None = None
    funnel_stage: str | None = None
    follow_up_script_id: int | None = None
    is_active: bool | None = None


@router.get("/", response_model=list[ScriptOut])
async def list_scripts(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
    type_id: int | None = None,
    include_inactive: bool = False,
):
    svc = ScriptService(db)
    return await svc.get_all_active(type_id=type_id, include_inactive=include_inactive)


@router.post("/", response_model=ScriptOut, status_code=201)
async def create_script(
    body: ScriptCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    svc = ScriptService(db)
    # Картинку по чужой ссылке забираем к себе сразу: ссылки на CDN ВК умирают
    # молча, и сообщение уходит без вложения (см. app.storage.rehost).
    script = await svc.create(
        body.condition, await rehost_external_photos(body.phrase_text), type_id=body.type_id,
        marketing_tag=body.marketing_tag or None,
        funnel_stage=body.funnel_stage or None,
        follow_up_script_id=body.follow_up_script_id or None,
    )
    await db.commit()
    await db.refresh(script)
    return script


@router.patch("/{script_id}", response_model=ScriptOut)
async def update_script(
    script_id: int,
    body: ScriptUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    svc = ScriptService(db)
    updates = body.model_dump(exclude_none=True)
    if updates.get("phrase_text"):
        updates["phrase_text"] = await rehost_external_photos(updates["phrase_text"])
    if "marketing_tag" in updates and not updates["marketing_tag"]:
        updates["marketing_tag"] = None  # empty string clears the tag
    if "funnel_stage" in updates and not updates["funnel_stage"]:
        updates["funnel_stage"] = None  # empty string clears the stage (= any stage)
    if "follow_up_script_id" in updates:
        # exclude_none выше съедает явный null, поэтому «связки нет» приходит нулём.
        if not updates["follow_up_script_id"]:
            updates["follow_up_script_id"] = None
        elif updates["follow_up_script_id"] == script_id:
            raise HTTPException(status_code=400, detail="Script cannot follow itself")
    script = await svc.update(script_id, **updates)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    await db.commit()
    await db.refresh(script)
    return script


@router.delete("/{script_id}", status_code=204)
async def delete_script(
    script_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    svc = ScriptService(db)
    if not await svc.delete(script_id):
        raise HTTPException(status_code=404, detail="Script not found")
    await db.commit()
