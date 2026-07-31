"""Tester chat API — simulate AI conversation without VK."""
import csv
import io
import uuid
from datetime import datetime

from app.utils.time import msk_now, to_naive_msk

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_type_access, get_allowed_type_ids, require_role
from app.storage.s3 import upload_file as s3_upload_file
from app.config import settings
from app.db.models import AIRun, Client, Dialog, DialogPingState, DialogStatusConfig, DialogType, Message, MessageFeedback, MessageRole, User
from app.db.session import get_db

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatStartRequest(BaseModel):
    vk_user_id: int
    client_name: str | None = None
    type_id: int | None = None
    ai_provider: str = settings.AI_PROVIDER
    # Аналог ref-метки из ВК: без неё в тестовом чате не проверить приветствия,
    # привязанные к тегу рекламной ссылки (sweetgold, ПАВЕЛ_ПАТРИОТ_1, ...).
    marketing_tag: str | None = None


class ChatMessageRequest(BaseModel):
    text: str
    files: list[str] = []


class ChatMessageOut(BaseModel):
    id: int
    role: str
    text: str
    created_at: datetime
    need_curator: bool = False
    confidence_score: float | None = None
    files: list[str] = []
    audio_urls: list[str] = []
    is_ping: bool = False
    feedback_id: int | None = None
    feedback_text: str | None = None
    selected_script: str | None = None
    source_script_id: int | None = None
    has_context: bool = False

    model_config = {"from_attributes": True}


class DialogListItem(BaseModel):
    id: int
    vk_user_id: int | None
    client_name: str | None
    marketing_tags: list[str] | None = None
    type_id: int | None
    current_status: str | None = None
    funnel_stage: str | None = None
    last_message_at: datetime | None
    created_at: datetime
    ai_provider: str = "openai"
    is_test: bool = True
    ai_paused: bool = False

    model_config = {"from_attributes": True}


async def _apply_dialog_filters(
    q,
    db: AsyncSession,
    *,
    is_test: bool | None,
    status_filter: list[str],
    ai_provider_filter: list[str],
    dialog_type_ids: list[int],
    date_from: datetime | None,
    date_to: datetime | None,
    vk_user_id: str | None,
    client_date_from: datetime | None,
    client_date_to: datetime | None,
    last_message_from: str | None,
    ping_funnel_type: str | None = None,
    funnel_stage: str | None = None,
    allowed_type_ids: list[int] | None = None,
):
    """Apply dialog list filters to a query that has Dialog and Client in scope.

    allowed_type_ids: None = без ограничений (админ); список (в т.ч. пустой) —
    жёсткий фильтр по направлениям пользователя, применяется поверх dialog_type_ids.
    """
    if allowed_type_ids is not None:
        q = q.where(Dialog.type_id.in_(allowed_type_ids))
    if is_test is not None:
        q = q.where(Dialog.is_test == is_test)
    if status_filter:
        want_no_status = "__none__" in status_filter
        names = [s for s in status_filter if s != "__none__"]
        conds = []
        if names:
            status_result = await db.execute(
                select(DialogStatusConfig.id).where(DialogStatusConfig.name.in_(names))
            )
            status_ids = status_result.scalars().all()
            if status_ids:
                conds.append(Dialog.current_status_id.in_(status_ids))
        if want_no_status:
            conds.append(Dialog.current_status_id.is_(None))
        if conds:
            q = q.where(or_(*conds))
    if ai_provider_filter:
        q = q.where(Dialog.ai_provider.in_(ai_provider_filter))
    if dialog_type_ids:
        q = q.where(Dialog.type_id.in_(dialog_type_ids))
    if date_from is not None:
        effective_date = func.coalesce(Dialog.last_message_at, Dialog.created_at)
        q = q.where(effective_date >= to_naive_msk(date_from))
    if date_to is not None:
        effective_date = func.coalesce(Dialog.last_message_at, Dialog.created_at)
        q = q.where(effective_date <= to_naive_msk(date_to))
    if vk_user_id:
        user_ids = [int(c.strip()) for c in vk_user_id.split(";") if c.strip().isdigit()]
        if user_ids:
            q = q.where(Client.vk_user_id.in_(user_ids))
    if client_date_from is not None:
        q = q.where(Client.created_at >= to_naive_msk(client_date_from))
    if client_date_to is not None:
        q = q.where(Client.created_at <= to_naive_msk(client_date_to))
    if ping_funnel_type:
        if ping_funnel_type == "__none__":
            no_ping_subq = select(DialogPingState.id).where(
                DialogPingState.dialog_id == Dialog.id
            )
            q = q.where(~no_ping_subq.exists())
        else:
            ping_subq = select(DialogPingState.id).where(
                DialogPingState.dialog_id == Dialog.id,
                DialogPingState.funnel_type == ping_funnel_type,
            )
            q = q.where(ping_subq.exists())
    if funnel_stage:
        if funnel_stage == "__none__":
            q = q.where(Dialog.funnel_stage.is_(None))
        else:
            q = q.where(Dialog.funnel_stage == funnel_stage)
    if last_message_from:
        last_role_subq = (
            select(Message.role)
            .where(Message.dialog_id == Dialog.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        if last_message_from in ("ai_reply", "ai_ping"):
            last_ping_subq = (
                select(func.coalesce(Message.msg_metadata["ping"].as_boolean(), False))
                .where(Message.dialog_id == Dialog.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
                .scalar_subquery()
            )
            q = q.where(last_role_subq == MessageRole.ai)
            q = q.where(last_ping_subq == (last_message_from == "ai_ping"))
        else:
            try:
                role_enum = MessageRole(last_message_from)
            except ValueError:
                role_enum = None
            if role_enum is not None:
                q = q.where(last_role_subq == role_enum)
    return q


@router.get("/ping-funnel-types")
async def list_ping_funnel_types(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "curator")),
):
    """Distinct funnel_type values from dialog_ping_states, for the filter select."""
    result = await db.execute(
        select(DialogPingState.funnel_type).distinct().order_by(DialogPingState.funnel_type)
    )
    return result.scalars().all()


@router.get("/dialogs/count")
async def count_chat_dialogs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
    is_test: bool | None = Query(default=None),
    status_filter: list[str] = Query(default=[]),
    ai_provider_filter: list[str] = Query(default=[]),
    dialog_type_ids: list[int] = Query(default=[]),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    vk_user_id: str | None = Query(default=None),
    client_date_from: datetime | None = Query(default=None),
    client_date_to: datetime | None = Query(default=None),
    last_message_from: str | None = Query(default=None),
    ping_funnel_type: str | None = Query(default=None),
    funnel_stage: str | None = Query(default=None),
):
    """Count dialogs matching the given filters."""
    q = select(func.count()).select_from(Dialog).join(Client, Dialog.client_id == Client.id)
    q = await _apply_dialog_filters(
        q, db,
        is_test=is_test, status_filter=status_filter, ai_provider_filter=ai_provider_filter,
        dialog_type_ids=dialog_type_ids, date_from=date_from, date_to=date_to,
        vk_user_id=vk_user_id, client_date_from=client_date_from,
        client_date_to=client_date_to, last_message_from=last_message_from,
        ping_funnel_type=ping_funnel_type, funnel_stage=funnel_stage,
        allowed_type_ids=await get_allowed_type_ids(current_user, db),
    )
    total = (await db.execute(q)).scalar_one()
    return {"count": total}


@router.get("/dialogs", response_model=list[DialogListItem])
async def list_chat_dialogs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
    is_test: bool | None = Query(default=None),
    status_filter: list[str] = Query(default=[]),
    ai_provider_filter: list[str] = Query(default=[]),
    dialog_type_ids: list[int] = Query(default=[]),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    vk_user_id: str | None = Query(default=None),
    client_date_from: datetime | None = Query(default=None),
    client_date_to: datetime | None = Query(default=None),
    last_message_from: str | None = Query(default=None),
    ping_funnel_type: str | None = Query(default=None),
    funnel_stage: str | None = Query(default=None),
    limit: int = 50,
    offset: int = 0,
):
    """List dialogs with client info, newest first."""
    q = (
        select(Dialog, Client, DialogStatusConfig.name.label("status_name"))
        .join(Client, Dialog.client_id == Client.id)
        .outerjoin(DialogStatusConfig, Dialog.current_status_id == DialogStatusConfig.id)
        .order_by(Dialog.last_message_at.desc().nullslast(), Dialog.created_at.desc())
    )
    q = await _apply_dialog_filters(
        q, db,
        is_test=is_test, status_filter=status_filter, ai_provider_filter=ai_provider_filter,
        dialog_type_ids=dialog_type_ids, date_from=date_from, date_to=date_to,
        vk_user_id=vk_user_id, client_date_from=client_date_from,
        client_date_to=client_date_to, last_message_from=last_message_from,
        ping_funnel_type=ping_funnel_type, funnel_stage=funnel_stage,
        allowed_type_ids=await get_allowed_type_ids(current_user, db),
    )
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.all()
    return [
        DialogListItem(
            id=dialog.id,
            vk_user_id=client.vk_user_id,
            client_name=client.name,
            marketing_tags=client.marketing_tags,
            type_id=dialog.type_id,
            current_status=status_name,
            funnel_stage=dialog.funnel_stage,
            last_message_at=dialog.last_message_at,
            created_at=dialog.created_at,
            ai_provider=dialog.ai_provider or "openai",
            is_test=dialog.is_test,
            ai_paused=dialog.ai_paused,
        )
        for dialog, client, status_name in rows
    ]


@router.get("/dialogs/export")
async def export_chat_dialogs_csv(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
    is_test: bool | None = Query(default=None),
    status_filter: list[str] = Query(default=[]),
    ai_provider_filter: list[str] = Query(default=[]),
    dialog_type_ids: list[int] = Query(default=[]),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    vk_user_id: str | None = Query(default=None),
    client_date_from: datetime | None = Query(default=None),
    client_date_to: datetime | None = Query(default=None),
    last_message_from: str | None = Query(default=None),
    ping_funnel_type: str | None = Query(default=None),
    funnel_stage: str | None = Query(default=None),
):
    """Export filtered dialogs as CSV."""
    q = (
        select(Dialog, Client, DialogStatusConfig.name.label("status_name"), Message)
        .join(Client, Dialog.client_id == Client.id)
        .outerjoin(DialogStatusConfig, Dialog.current_status_id == DialogStatusConfig.id)
        .outerjoin(Message, Message.dialog_id == Dialog.id)
        .order_by(Dialog.last_message_at.desc().nullslast(), Dialog.created_at.desc(), Message.created_at.asc())
    )
    allowed = await get_allowed_type_ids(current_user, db)
    if allowed is not None:
        q = q.where(Dialog.type_id.in_(allowed))
    if is_test is not None:
        q = q.where(Dialog.is_test == is_test)
    if status_filter:
        want_no_status = "__none__" in status_filter
        names = [s for s in status_filter if s != "__none__"]
        conds = []
        if names:
            status_result = await db.execute(
                select(DialogStatusConfig.id).where(DialogStatusConfig.name.in_(names))
            )
            status_ids = status_result.scalars().all()
            if status_ids:
                conds.append(Dialog.current_status_id.in_(status_ids))
        if want_no_status:
            conds.append(Dialog.current_status_id.is_(None))
        if conds:
            q = q.where(or_(*conds))
    if ai_provider_filter:
        q = q.where(Dialog.ai_provider.in_(ai_provider_filter))
    if dialog_type_ids:
        q = q.where(Dialog.type_id.in_(dialog_type_ids))
    if date_from is not None:
        effective_date = func.coalesce(Dialog.last_message_at, Dialog.created_at)
        q = q.where(effective_date >= to_naive_msk(date_from))
    if date_to is not None:
        effective_date = func.coalesce(Dialog.last_message_at, Dialog.created_at)
        q = q.where(effective_date <= to_naive_msk(date_to))
    if vk_user_id:
        user_ids = [int(c.strip()) for c in vk_user_id.split(";") if c.strip().isdigit()]
        if user_ids:
            q = q.where(Client.vk_user_id.in_(user_ids))
    if client_date_from is not None:
        q = q.where(Client.created_at >= to_naive_msk(client_date_from))
    if client_date_to is not None:
        q = q.where(Client.created_at <= to_naive_msk(client_date_to))
    if ping_funnel_type:
        if ping_funnel_type == "__none__":
            no_ping_subq = select(DialogPingState.id).where(
                DialogPingState.dialog_id == Dialog.id
            )
            q = q.where(~no_ping_subq.exists())
        else:
            ping_subq = select(DialogPingState.id).where(
                DialogPingState.dialog_id == Dialog.id,
                DialogPingState.funnel_type == ping_funnel_type,
            )
            q = q.where(ping_subq.exists())
    if funnel_stage:
        if funnel_stage == "__none__":
            q = q.where(Dialog.funnel_stage.is_(None))
        else:
            q = q.where(Dialog.funnel_stage == funnel_stage)
    if last_message_from:
        try:
            role_enum = MessageRole(last_message_from)
        except ValueError:
            role_enum = None
        if role_enum is not None:
            last_role_subq = (
                select(Message.role)
                .where(Message.dialog_id == Dialog.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
                .scalar_subquery()
            )
            q = q.where(last_role_subq == role_enum)

    result = await db.execute(q)
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "dialog_id", "vk_user_id", "client_name", "type_id", "current_status",
        "dialog_created_at", "last_message_at", "ai_provider", "is_test",
        "message_id", "message_role", "message_text", "message_created_at",
    ])
    for dialog, client, status_name, message in rows:
        writer.writerow([
            dialog.id,
            client.vk_user_id,
            client.name,
            dialog.type_id,
            status_name or "",
            dialog.created_at.isoformat(),
            dialog.last_message_at.isoformat() if dialog.last_message_at else "",
            dialog.ai_provider or "openai",
            dialog.is_test,
            message.id if message else "",
            message.role.value if message else "",
            message.text if message else "",
            message.created_at.isoformat() if message else "",
        ])

    output.seek(0)
    filename = f"dialogs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/dialogs/export-ids")
async def export_chat_client_ids(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
    is_test: bool | None = Query(default=None),
    status_filter: list[str] = Query(default=[]),
    ai_provider_filter: list[str] = Query(default=[]),
    dialog_type_ids: list[int] = Query(default=[]),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    vk_user_id: str | None = Query(default=None),
    client_date_from: datetime | None = Query(default=None),
    client_date_to: datetime | None = Query(default=None),
    last_message_from: str | None = Query(default=None),
    ping_funnel_type: str | None = Query(default=None),
    funnel_stage: str | None = Query(default=None),
):
    """Export distinct vk_user_ids of filtered dialogs, joined by ';'."""
    q = (
        select(Client.vk_user_id)
        .select_from(Dialog)
        .join(Client, Dialog.client_id == Client.id)
        .distinct()
    )
    q = await _apply_dialog_filters(
        q, db,
        is_test=is_test, status_filter=status_filter, ai_provider_filter=ai_provider_filter,
        dialog_type_ids=dialog_type_ids, date_from=date_from, date_to=date_to,
        vk_user_id=vk_user_id, client_date_from=client_date_from,
        client_date_to=client_date_to, last_message_from=last_message_from,
        ping_funnel_type=ping_funnel_type, funnel_stage=funnel_stage,
        allowed_type_ids=await get_allowed_type_ids(current_user, db),
    )
    result = await db.execute(q)
    client_ids = [str(cid) for cid in result.scalars().all() if cid]
    content = ";".join(client_ids)
    filename = f"client_ids_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return StreamingResponse(
        iter([content]),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/start")
async def start_chat(
    body: ChatStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Return existing dialog for this client+type, or create one.

    Тестовые клиенты живут без привязки к группе (vk_group_id IS NULL) и не
    пересекаются с реальными клиентами вебхука."""
    result = await db.execute(
        select(Client).where(
            Client.vk_user_id == body.vk_user_id,
            Client.vk_group_id.is_(None),
        )
    )
    client = result.scalar_one_or_none()
    tag = (body.marketing_tag or "").strip() or None
    if not client:
        client = Client(
            vk_user_id=body.vk_user_id,
            name=body.client_name or str(body.vk_user_id),
            source="test_chat",
            marketing_tags=[tag] if tag else None,
        )
        db.add(client)
        await db.flush()
    elif tag and client.marketing_tags != [tag]:
        # Тестировщик перезапускает того же клиента под другой рекламной меткой.
        client.marketing_tags = [tag]
        await db.flush()

    # Resolve effective type_id: use provided or fall back to first active type
    effective_type_id = body.type_id
    if effective_type_id is None:
        type_result = await db.execute(
            select(DialogType).where(DialogType.is_active == True).order_by(DialogType.id)
        )
        default_type = type_result.scalar_one_or_none()
        effective_type_id = default_type.id if default_type else None
    await ensure_type_access(current_user, effective_type_id, db)

    existing = await db.execute(
        select(Dialog).where(
            Dialog.client_id == client.id,
            Dialog.type_id == effective_type_id,
        )
    )
    dialog = existing.scalar_one_or_none()

    if not dialog:
        dialog = Dialog(
            client_id=client.id,
            type_id=effective_type_id,
            current_status_id=None,
            is_test=True,
            assigned_curator_id=current_user.id,
            ai_provider=body.ai_provider,
        )
        db.add(dialog)
        await db.flush()

    await db.commit()

    return {
        "dialog_id": dialog.id,
        "client_id": client.id,
        "vk_user_id": client.vk_user_id,
        "client_name": client.name,
    }


@router.post("/{dialog_id}/upload")
async def upload_file(
    dialog_id: int,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)
    if not dialog.is_test:
        raise HTTPException(status_code=403, detail="Not a test dialog")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File cannot be empty")
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    filename = f"chat/{dialog_id}/{uuid.uuid4().hex}.{ext}"
    url = await s3_upload_file(data, filename, content_type=file.content_type or "image/jpeg")
    return {"url": url}


@router.post("/{dialog_id}/message", response_model=list[ChatMessageOut])
async def send_message(
    dialog_id: int,
    body: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)
    if not dialog.is_test:
        raise HTTPException(status_code=403, detail="Not a test dialog")

    client_message = Message(
        dialog_id=dialog_id,
        role=MessageRole.client,
        text=body.text.strip(),
        msg_metadata={"files": body.files} if body.files else None,
    )
    db.add(client_message)
    dialog.last_message_at = msk_now()
    await db.flush()
    await db.commit()

    # ИИ на паузе (оператор перехватил диалог или сработала эскалация к менеджеру) —
    # сообщение сохраняем, но не отвечаем. То же поведение, что в вебхуке ВК, иначе
    # в тестовом чате эскалация выглядела бы иначе, чем на живом трафике.
    if dialog.ai_paused:
        n_parts = 0
    else:
        from app.ai.runner import run_ai
        output, ai_run, parts = await run_ai(db, dialog, client_message)
        n_parts = len(parts)

    # Реплика клиента + все реплики хода: связка скриптов даёт больше одной
    # (приветствие, следом вопрос про имя/фамилию), и тестировщик должен увидеть
    # ровно то, что ушло бы клиенту в ВК.
    result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1 + n_parts)
    )
    messages = list(reversed(result.scalars().all()))

    out = []
    for m in messages:
        need_curator = False
        confidence = None
        files: list[str] = []
        is_ping = False
        audio_urls: list[str] = []
        if m.msg_metadata:
            need_curator = m.msg_metadata.get("need_curator", False)
            confidence = m.msg_metadata.get("confidence")
            files = m.msg_metadata.get("files", [])
            audio_urls = m.msg_metadata.get("audio_urls", [])
            is_ping = bool(m.msg_metadata.get("ping", False))
        out.append(ChatMessageOut(
            id=m.id,
            role=m.role.value,
            text=m.text,
            created_at=m.created_at,
            need_curator=need_curator,
            confidence_score=confidence,
            files=files,
            audio_urls=audio_urls,
            is_ping=is_ping,
        ))

    return out


@router.delete("/dialogs")
async def delete_all_dialogs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Delete all test dialogs and their messages (в рамках доступных направлений)."""
    q = select(Dialog.id).where(Dialog.is_test == True)
    allowed = await get_allowed_type_ids(current_user, db)
    if allowed is not None:
        q = q.where(Dialog.type_id.in_(allowed))
    result = await db.execute(q)
    dialog_ids = result.scalars().all()
    if dialog_ids:
        await db.execute(Dialog.__table__.delete().where(Dialog.id.in_(dialog_ids)))
        await db.commit()
    return {"deleted": len(dialog_ids)}


@router.delete("/{dialog_id}")
async def delete_dialog(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog or not dialog.is_test:
        raise HTTPException(status_code=404, detail="Test dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)
    await db.delete(dialog)
    await db.commit()
    return {"deleted": dialog_id}


@router.get("/{dialog_id}/history", response_model=list[ChatMessageOut])
async def get_history(
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
    messages = result.scalars().all()

    message_ids = [m.id for m in messages]
    feedbacks: dict[int, MessageFeedback] = {}
    ai_runs_by_msg: dict[int, AIRun] = {}
    if message_ids:
        fb_result = await db.execute(
            select(MessageFeedback).where(MessageFeedback.message_id.in_(message_ids))
        )
        for fb in fb_result.scalars().all():
            feedbacks[fb.message_id] = fb
        run_result = await db.execute(
            select(AIRun).where(AIRun.output_message_id.in_(message_ids))
        )
        for run in run_result.scalars().all():
            ai_runs_by_msg[run.output_message_id] = run

    out = []
    for m in messages:
        need_curator = False
        confidence = None
        files: list[str] = []
        is_ping = False
        audio_urls: list[str] = []
        if m.msg_metadata:
            need_curator = m.msg_metadata.get("need_curator", False)
            confidence = m.msg_metadata.get("confidence")
            files = m.msg_metadata.get("files", [])
            audio_urls = m.msg_metadata.get("audio_urls", [])
            is_ping = bool(m.msg_metadata.get("ping", False))
        fb = feedbacks.get(m.id)
        run = ai_runs_by_msg.get(m.id)
        out.append(ChatMessageOut(
            id=m.id,
            role=m.role.value,
            text=m.text,
            created_at=m.created_at,
            need_curator=need_curator,
            confidence_score=confidence,
            files=files,
            audio_urls=audio_urls,
            is_ping=is_ping,
            feedback_id=fb.id if fb else None,
            feedback_text=fb.rule_text if fb else None,
            selected_script=run.selected_script if run else None,
            source_script_id=run.source_script_id if run else None,
            has_context=bool(run and run.full_context),
        ))

    return out


@router.get("/run-context/{message_id}")
async def get_run_context(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Full AI context (system prompt + messages) used to produce the given AI message."""
    run_result = await db.execute(
        select(AIRun)
        .where(AIRun.output_message_id == message_id)
        .order_by(AIRun.created_at.desc())
    )
    run = run_result.scalars().first()
    if not run or not run.full_context:
        raise HTTPException(status_code=404, detail="Context not found")
    dialog = await db.get(Dialog, run.dialog_id)
    await ensure_type_access(current_user, dialog.type_id if dialog else None, db)
    return {
        "message_id": message_id,
        "provider": run.provider,
        "model": run.model,
        "full_context": run.full_context,
    }
