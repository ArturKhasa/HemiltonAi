"""Tester chat API — simulate AI conversation without VK."""
import csv
import io
import logging
import uuid
from datetime import datetime

from app.utils.time import msk_now, to_naive_msk

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_type_access, get_allowed_type_ids, require_role
from app.storage.local import safe_extension, save_file
from app.config import settings
from app.utils.media import attachment_token
from app.utils.text import person_label as _person
from app.db.models import AIRun, Client, Dialog, DialogPingState, DialogStatusConfig, DialogType, Message, MessageFeedback, MessageRole, User, UserDialogType, UserRole, VkGroup
from app.db.session import get_db

logger = logging.getLogger(__name__)

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
    # Тема, из-за которой диалог передан менеджеру («вышивка», «опт»). Метка
    # только для админки — клиенту в ВК уходит обычный текст ответа.
    curator_trigger: str | None = None
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
    # Фамилия отдельно: в диалоге по ней не обращаются, а в списке лидов она
    # нужна рядом с именем — раньше первой строкой там стоял числовой VK ID.
    client_last_name: str | None = None
    marketing_tags: list[str] | None = None
    type_id: int | None
    current_status: str | None = None
    funnel_stage: str | None = None
    last_message_at: datetime | None
    created_at: datetime
    ai_provider: str = "openai"
    is_test: bool = True
    ai_paused: bool = False
    # Мессенджер клиента. В списке ВК и MAX были неотличимы, хотя ведут себя
    # по-разному: в MAX клиент получает приветствие и цену, не написав ни строчки,
    # а менеджер отвечает мимо панели. MAX-лид в общем списке терялся полностью —
    # 428 диалогов против 79 446 за две недели.
    platform: str = "vk"
    # По диалогу идут пинги и будут идти дальше. Воронка, once completed, заново
    # не заводится (см. ping.worker.discover), поэтому признак честный: красная
    # метка не обещает пинга, которого не будет.
    ping_active: bool = False
    ping_next_at: datetime | None = None
    # Ответственный менеджер. Лена просила его дважды (25.08, 26.08) и просила
    # брать из BlueSales; интеграции не будет, поэтому назначаем в панели руками.
    # Колонка dialogs.assigned_curator_id лежала в базе с первой миграции и
    # никем не использовалась.
    assignee_id: int | None = None
    assignee_name: str | None = None

    model_config = {"from_attributes": True}


def _ping_active(dialog: Dialog, ping_completed: bool | None) -> bool:
    """Пинги по диалогу идут и будут идти дальше.

    Воронки нет (`ping_completed is None`) или она закрыта — пингов не будет:
    заново воронка не заводится, `discover()` пропускает диалоги, у которых
    запись уже есть. Пауза ИИ и блокировка отправки закроют воронку на ближайшем
    проходе воркера, поэтому метку снимаем сразу — иначе она обещала бы пинг,
    которого не будет.
    """
    if ping_completed is None or ping_completed:
        return False
    return not dialog.ai_paused and not dialog.vk_blocked


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
    client_name: str | None = None,
    ping_funnel_type: str | None = None,
    funnel_stage: str | None = None,
    marketing_tag: list[str] | None = None,
    ping_active: bool | None = None,
    platform: list[str] | None = None,
    assignee: list[str] | None = None,
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
    if client_name:
        # Каждое слово запроса должно найтись в имени ИЛИ фамилии: менеджер ищет
        # «Аксёнов Денис», а в базе имя и фамилия лежат раздельно и в любом
        # порядке — «Денис Аксёнов» должно находиться тем же запросом.
        for word in client_name.split():
            pattern = f"%{word}%"
            q = q.where(or_(
                Client.name.ilike(pattern), Client.last_name.ilike(pattern),
            ))
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
    if marketing_tag:
        want_no_tag = "__none__" in marketing_tag
        tags = [t for t in marketing_tag if t != "__none__"]
        conds = []
        if tags:
            # Метка у клиента ровно одна: её ставит вебхук из ref-ссылки
            # (app.vk.webhook), списком поле сделано на будущее. Берём нулевой
            # элемент, а не containment: `->> 0` есть и в JSONB на проде, и в
            # JSON на SQLite в тестах, а `@>` — только в Postgres.
            conds.append(Client.marketing_tags[0].as_string().in_(tags))
        if want_no_tag:
            # Метки нет вовсе — клиент пришёл из поиска по группе, а не с рекламы.
            # Тем же выражением, что и выше: `->> 0` даёт NULL и когда колонка
            # NULL, и когда массив пустой — оба случая в базе встречаются.
            conds.append(Client.marketing_tags[0].as_string().is_(None))
        if conds:
            q = q.where(or_(*conds))
    if ping_active is not None:
        # «Пинги идут» = воронка заведена и не закрыта, И диалог не забрал живой
        # оператор, И отправка не заблокирована. Последние два условия — те же,
        # по которым воронку закроет воркер (ping.worker._process_state), но
        # узнает он об этом только на своём ближайшем проходе. Без них метка
        # висела бы на диалогах, где пинга уже не будет.
        active_ping = (
            select(DialogPingState.id)
            .where(
                DialogPingState.dialog_id == Dialog.id,
                DialogPingState.is_completed == False,
            )
            # correlate(Dialog) обязателен: список диалогов сам джойнит
            # dialog_ping_states ради колонок метки, и без явного указания
            # SQLAlchemy соотносит с внешним запросом ОБЕ таблицы — подзапрос
            # остаётся без FROM и падает.
            .correlate(Dialog)
            .exists()
        )
        alive = Dialog.ai_paused == False
        condition = active_ping & alive & (Dialog.vk_blocked == False)
        q = q.where(condition if ping_active else ~condition)
    if platform:
        # Платформа лежит на канале клиента. Тестовый диалог из панели канала не
        # имеет вовсе — считаем его ВК, как и везде (messaging.platform_of).
        conds = []
        if "vk" in platform:
            conds.append(or_(VkGroup.platform == "vk", VkGroup.platform.is_(None)))
        for name in platform:
            if name != "vk":
                conds.append(VkGroup.platform == name)
        if conds:
            q = q.where(or_(*conds))
    if assignee:
        want_nobody = "__none__" in assignee
        ids = [int(a) for a in assignee if a != "__none__" and a.lstrip("-").isdigit()]
        conds = []
        if ids:
            conds.append(Dialog.assigned_curator_id.in_(ids))
        if want_nobody:
            conds.append(Dialog.assigned_curator_id.is_(None))
        if conds:
            q = q.where(or_(*conds))
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


class AssigneeOut(BaseModel):
    id: int
    label: str
    role: str


class AssigneeRequest(BaseModel):
    # None — снять ответственного.
    user_id: int | None = None


@router.get("/assignees", response_model=list[AssigneeOut])
async def list_assignees(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Кого можно назначить ответственным за диалог.

    Куратора показываем только вместе с его направлениями: назначать человека на
    диалог, которого он не увидит, смысла нет. Админ виден всегда — он видит всё.
    """
    allowed = await get_allowed_type_ids(current_user, db)
    rows = (await db.execute(select(User).order_by(User.id))).scalars().all()
    by_user = {}
    if allowed is not None:
        links = await db.execute(
            select(UserDialogType.user_id, UserDialogType.type_id)
        )
        for user_id, type_id in links.all():
            by_user.setdefault(user_id, set()).add(type_id)

    out = []
    for u in rows:
        if allowed is not None and u.role != UserRole.admin:
            if not (by_user.get(u.id) or set()) & set(allowed):
                continue
        out.append(AssigneeOut(
            id=u.id, label=_person(u.name, u.email) or str(u.id), role=u.role.value,
        ))
    return out


@router.post("/dialogs/{dialog_id}/assignee")
async def set_assignee(
    dialog_id: int,
    body: AssigneeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Назначить ответственного менеджера или снять его (`user_id: null`)."""
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)

    label = None
    if body.user_id is not None:
        user = await db.get(User, body.user_id)
        if not user:
            raise HTTPException(status_code=400, detail="Unknown user")
        label = _person(user.name, user.email)
    dialog.assigned_curator_id = body.user_id
    dialog.updated_at = msk_now()
    await db.commit()
    logger.info(
        "[dialog=%s] ответственный: %s | назначил user=%s",
        dialog_id, label or "снят", current_user.id,
    )
    return {"ok": True, "assignee_id": body.user_id, "assignee_name": label}


@router.get("/marketing-tags")
async def list_marketing_tags(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Метки рекламных ссылок, встреченные у клиентов, — для фильтра списка.

    Сортировка по числу диалогов, а не по алфавиту: сверху оказывается то, чем
    отдел продаж пользуется каждый день, а не старая кампания на букву «а».
    Считаем только по диалогам доступных пользователю направлений — иначе
    куратор увидел бы в фильтре метки чужого направления.
    """
    tag = Client.marketing_tags[0].as_string().label("tag")
    q = (
        select(tag)
        .select_from(Dialog)
        .join(Client, Dialog.client_id == Client.id)
        .where(tag.is_not(None))
    )
    allowed = await get_allowed_type_ids(current_user, db)
    if allowed is not None:
        q = q.where(Dialog.type_id.in_(allowed))
    q = q.group_by(tag).order_by(func.count().desc(), tag)
    return list((await db.execute(q)).scalars().all())


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
    client_name: str | None = Query(default=None),
    client_date_from: datetime | None = Query(default=None),
    client_date_to: datetime | None = Query(default=None),
    last_message_from: str | None = Query(default=None),
    ping_funnel_type: str | None = Query(default=None),
    funnel_stage: str | None = Query(default=None),
    marketing_tag: list[str] = Query(default=[]),
    ping_active: bool | None = Query(default=None),
    platform: list[str] = Query(default=[]),
    assignee: list[str] = Query(default=[]),
):
    """Count dialogs matching the given filters."""
    q = (
        select(func.count())
        .select_from(Dialog)
        .join(Client, Dialog.client_id == Client.id)
        # Канал — ради фильтра по платформе. outerjoin: у тестового диалога из
        # панели канала нет вовсе.
        .outerjoin(VkGroup, Client.vk_group_id == VkGroup.id)
    )
    q = await _apply_dialog_filters(
        q, db,
        is_test=is_test, status_filter=status_filter, ai_provider_filter=ai_provider_filter,
        dialog_type_ids=dialog_type_ids, date_from=date_from, date_to=date_to,
        vk_user_id=vk_user_id, client_name=client_name,
        client_date_from=client_date_from,
        client_date_to=client_date_to, last_message_from=last_message_from,
        ping_funnel_type=ping_funnel_type, funnel_stage=funnel_stage,
        marketing_tag=marketing_tag,
        ping_active=ping_active,
        platform=platform,
        assignee=assignee,
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
    client_name: str | None = Query(default=None),
    client_date_from: datetime | None = Query(default=None),
    client_date_to: datetime | None = Query(default=None),
    last_message_from: str | None = Query(default=None),
    ping_funnel_type: str | None = Query(default=None),
    funnel_stage: str | None = Query(default=None),
    marketing_tag: list[str] = Query(default=[]),
    ping_active: bool | None = Query(default=None),
    platform: list[str] = Query(default=[]),
    assignee: list[str] = Query(default=[]),
    limit: int = 50,
    offset: int = 0,
):
    """List dialogs with client info, newest first."""
    q = (
        select(
            Dialog,
            Client,
            DialogStatusConfig.name.label("status_name"),
            VkGroup.platform,
            DialogPingState.is_completed,
            DialogPingState.next_ping_due_at,
            User.name.label("assignee_name"),
            User.email.label("assignee_email"),
        )
        .join(Client, Dialog.client_id == Client.id)
        .outerjoin(DialogStatusConfig, Dialog.current_status_id == DialogStatusConfig.id)
        .outerjoin(VkGroup, Client.vk_group_id == VkGroup.id)
        # Воронка пингов — одна на диалог (уникальный dialog_id), лишних строк
        # join не даст.
        .outerjoin(DialogPingState, DialogPingState.dialog_id == Dialog.id)
        .outerjoin(User, Dialog.assigned_curator_id == User.id)
        .order_by(Dialog.last_message_at.desc().nullslast(), Dialog.created_at.desc())
    )
    q = await _apply_dialog_filters(
        q, db,
        is_test=is_test, status_filter=status_filter, ai_provider_filter=ai_provider_filter,
        dialog_type_ids=dialog_type_ids, date_from=date_from, date_to=date_to,
        vk_user_id=vk_user_id, client_name=client_name,
        client_date_from=client_date_from,
        client_date_to=client_date_to, last_message_from=last_message_from,
        ping_funnel_type=ping_funnel_type, funnel_stage=funnel_stage,
        marketing_tag=marketing_tag,
        ping_active=ping_active,
        platform=platform,
        assignee=assignee,
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
            client_last_name=client.last_name,
            marketing_tags=client.marketing_tags,
            type_id=dialog.type_id,
            current_status=status_name,
            funnel_stage=dialog.funnel_stage,
            last_message_at=dialog.last_message_at,
            created_at=dialog.created_at,
            ai_provider=dialog.ai_provider or "openai",
            is_test=dialog.is_test,
            ai_paused=dialog.ai_paused,
            platform=platform or "vk",
            ping_active=_ping_active(dialog, ping_completed),
            ping_next_at=next_ping_at,
            assignee_id=dialog.assigned_curator_id,
            assignee_name=_person(assignee_name, assignee_email),
        )
        for (
            dialog, client, status_name, platform, ping_completed, next_ping_at,
            assignee_name, assignee_email,
        ) in rows
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
    client_name: str | None = Query(default=None),
    client_date_from: datetime | None = Query(default=None),
    client_date_to: datetime | None = Query(default=None),
    last_message_from: str | None = Query(default=None),
    ping_funnel_type: str | None = Query(default=None),
    funnel_stage: str | None = Query(default=None),
    marketing_tag: list[str] = Query(default=[]),
    ping_active: bool | None = Query(default=None),
    platform: list[str] = Query(default=[]),
    assignee: list[str] = Query(default=[]),
):
    """Export filtered dialogs as CSV.

    Фильтры берём из общей `_apply_dialog_filters`: раньше выгрузка повторяла их
    копипастой и уже разъехалась со списком (в копии не было разделения
    ai_reply/ai_ping), а каждый новый фильтр приходилось дописывать дважды.
    """
    q = (
        select(
            Dialog,
            Client,
            DialogStatusConfig.name.label("status_name"),
            Message,
            VkGroup.platform,
            DialogPingState.is_completed,
            User.name.label("assignee_name"),
            User.email.label("assignee_email"),
        )
        .join(Client, Dialog.client_id == Client.id)
        .outerjoin(DialogStatusConfig, Dialog.current_status_id == DialogStatusConfig.id)
        .outerjoin(VkGroup, Client.vk_group_id == VkGroup.id)
        .outerjoin(DialogPingState, DialogPingState.dialog_id == Dialog.id)
        .outerjoin(User, Dialog.assigned_curator_id == User.id)
        .outerjoin(Message, Message.dialog_id == Dialog.id)
        .order_by(Dialog.last_message_at.desc().nullslast(), Dialog.created_at.desc(), Message.created_at.asc())
    )
    q = await _apply_dialog_filters(
        q, db,
        is_test=is_test, status_filter=status_filter, ai_provider_filter=ai_provider_filter,
        dialog_type_ids=dialog_type_ids, date_from=date_from, date_to=date_to,
        vk_user_id=vk_user_id, client_name=client_name,
        client_date_from=client_date_from,
        client_date_to=client_date_to, last_message_from=last_message_from,
        ping_funnel_type=ping_funnel_type, funnel_stage=funnel_stage,
        marketing_tag=marketing_tag,
        ping_active=ping_active,
        platform=platform,
        assignee=assignee,
        allowed_type_ids=await get_allowed_type_ids(current_user, db),
    )

    result = await db.execute(q)
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "dialog_id", "vk_user_id", "client_name", "client_last_name", "marketing_tag",
        "platform", "ping_active", "assignee", "type_id", "current_status",
        "dialog_created_at", "last_message_at", "ai_provider", "is_test",
        "message_id", "message_role", "message_text", "message_created_at",
    ])
    for (
        dialog, client, status_name, message, platform, ping_completed,
        assignee_name, assignee_email,
    ) in rows:
        writer.writerow([
            dialog.id,
            client.vk_user_id,
            client.name,
            client.last_name,
            (client.marketing_tags or [""])[0],
            platform or "vk",
            _ping_active(dialog, ping_completed),
            _person(assignee_name, assignee_email) or "",
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
    client_name: str | None = Query(default=None),
    client_date_from: datetime | None = Query(default=None),
    client_date_to: datetime | None = Query(default=None),
    last_message_from: str | None = Query(default=None),
    ping_funnel_type: str | None = Query(default=None),
    funnel_stage: str | None = Query(default=None),
    marketing_tag: list[str] = Query(default=[]),
    ping_active: bool | None = Query(default=None),
    platform: list[str] = Query(default=[]),
    assignee: list[str] = Query(default=[]),
):
    """Export distinct vk_user_ids of filtered dialogs, joined by ';'."""
    q = (
        select(Client.vk_user_id)
        .select_from(Dialog)
        .join(Client, Dialog.client_id == Client.id)
        .outerjoin(VkGroup, Client.vk_group_id == VkGroup.id)
        .distinct()
    )
    q = await _apply_dialog_filters(
        q, db,
        is_test=is_test, status_filter=status_filter, ai_provider_filter=ai_provider_filter,
        dialog_type_ids=dialog_type_ids, date_from=date_from, date_to=date_to,
        vk_user_id=vk_user_id, client_name=client_name,
        client_date_from=client_date_from,
        client_date_to=client_date_to, last_message_from=last_message_from,
        ping_funnel_type=ping_funnel_type, funnel_stage=funnel_stage,
        marketing_tag=marketing_tag,
        ping_active=ping_active,
        platform=platform,
        assignee=assignee,
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
    # Раньше сюда пускали только тестовые диалоги. Менеджеру, который отвечает
    # клиенту в ВК, тоже есть что приложить — фото готового изделия, макет,
    # видео со склада (просьба ОП от 18.08).
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File cannot be empty")
    limit = settings.MEDIA_MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(
            status_code=413, detail=f"Файл больше {settings.MEDIA_MAX_UPLOAD_MB} МБ",
        )
    key = f"chat/{dialog_id}/{uuid.uuid4().hex}.{safe_extension(file.filename)}"
    url = await save_file(data, key, content_type=file.content_type or "image/jpeg")
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

    from app.ai.dialog_lock import dialog_lock, superseded_by_newer_message

    # Блокировка та же, что в вебхуке: тестировщик отправляет вторую реплику, не
    # дождавшись ответа на первую, и без неё получал два параллельных прогона.
    async with dialog_lock(dialog.id):
        await db.refresh(dialog)
        # ИИ на паузе (оператор перехватил диалог или сработала эскалация к менеджеру) —
        # сообщение сохраняем, но не отвечаем. То же поведение, что в вебхуке ВК, иначе
        # в тестовом чате эскалация выглядела бы иначе, чем на живом трафике.
        if dialog.ai_paused or await superseded_by_newer_message(
            db, dialog.id, client_message.id
        ):
            n_parts = 0
        else:
            from app.ai.runner import run_ai
            output, ai_run, parts = await run_ai(db, dialog, client_message)
            n_parts = len(parts)
            # В тестовом диалоге отправки в мессенджер нет, поэтому лестницу
            # двигаем сразу: иначе статусы в панели вели бы себя не так, как на
            # живом трафике, и проверить воронку было бы негде.
            from app.sales.status_flow import sync_status

            await sync_status(db, dialog, ctx=f"test dialog={dialog.id}")
            await db.commit()

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
        curator_trigger = None
        if m.msg_metadata:
            need_curator = m.msg_metadata.get("need_curator", False)
            confidence = m.msg_metadata.get("confidence")
            files = m.msg_metadata.get("files", [])
            audio_urls = m.msg_metadata.get("audio_urls", [])
            is_ping = bool(m.msg_metadata.get("ping", False))
            curator_trigger = m.msg_metadata.get("curator_trigger")
        out.append(ChatMessageOut(
            id=m.id,
            role=m.role.value,
            text=m.text,
            created_at=m.created_at,
            need_curator=need_curator,
            curator_trigger=curator_trigger,
            confidence_score=confidence,
            files=files,
            audio_urls=audio_urls,
            is_ping=is_ping,
        ))

    return out


@router.post("/{dialog_id}/reply", response_model=ChatMessageOut)
async def reply_as_manager(
    dialog_id: int,
    body: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator")),
):
    """Ответ живого менеджера клиенту прямо из панели.

    До этого написать в боевой диалог было неоткуда: эндпоинт выше обслуживает
    только тестовые диалоги (там сообщение изображает КЛИЕНТА и запускает ИИ), а
    в ВК менеджер уходил из нашего поля зрения совсем. Диалог с меткой «Нужен
    куратор» было видно, а сделать с ним что-либо — нельзя.

    Отправка сама забирает диалог у ИИ: ставит паузу и гасит пинги. Вернуть ИИ
    можно тумблером (см. dialogs.set_ai_pause).
    """
    from app.ping.worker import stop_pings
    from app.vk.outgoing import mark_delivered, mark_failed
    from app.messaging import MessagesForbiddenError, send_to_dialog

    text = (body.text or "").strip()
    # Одно вложение без подписи — нормальный ответ менеджера: «вот как выглядит»
    # и фотография. Пустым такое сообщение не считаем.
    if not text and not body.files:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await ensure_type_access(current_user, dialog.type_id, db)

    # Файлы уходят вложением, а не ссылкой в тексте: ссылку клиент видит как
    # набор символов, а вложение ВК показывает картинкой или файлом.
    outgoing = text
    if body.files:
        tokens = "\n".join(attachment_token(u) for u in body.files)
        outgoing = (outgoing + "\n\n" + tokens).strip()

    message = Message(
        dialog_id=dialog_id,
        role=MessageRole.curator,
        text=text,
        msg_metadata={"files": body.files, "sent_by_user_id": current_user.id},
    )
    db.add(message)

    # Паузу ставим ДО отправки: пока идёт запрос в ВК, входящее сообщение
    # клиента может запустить прогон, и ИИ ответит поверх менеджера.
    if not dialog.ai_paused:
        dialog.ai_paused = True
    await stop_pings(db, dialog.id, f"ответ менеджера из панели (user={current_user.id})")
    await db.flush()

    if dialog.is_test:
        # В тестовом диалоге клиента в ВК нет — сообщение живёт только в панели.
        mark_delivered(message, None)
    else:
        try:
            result = await send_to_dialog(db, dialog, outgoing)
        except MessagesForbiddenError:
            mark_failed(message)
            await db.commit()
            raise HTTPException(status_code=409, detail="Клиент запретил сообщения от бота или сообщества")
        except Exception as exc:
            mark_failed(message)
            await db.commit()
            raise HTTPException(status_code=502, detail=f"Мессенджер не принял сообщение: {exc}")
        mark_delivered(message, result)

    dialog.last_message_at = msk_now()
    # Менеджер тоже двигает воронку: цену, способы оплаты и счёт он отправляет
    # руками, и статус должен это видеть — 665 диалогов ведёт живой оператор при
    # выключенном ИИ, и ступени им нужны ровно так же.
    from app.sales.status_flow import sync_status

    await sync_status(db, dialog, ctx=f"manager dialog={dialog.id}")
    await db.commit()
    await db.refresh(message)

    logger.info(
        "[dialog=%s] ответ менеджера отправлен | user=%s | ai_paused=True",
        dialog_id, current_user.id,
    )
    return ChatMessageOut(
        id=message.id,
        role=message.role.value,
        text=message.text,
        created_at=message.created_at,
        need_curator=False,
        files=body.files,
    )


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
        curator_trigger = None
        if m.msg_metadata:
            need_curator = m.msg_metadata.get("need_curator", False)
            confidence = m.msg_metadata.get("confidence")
            files = m.msg_metadata.get("files", [])
            audio_urls = m.msg_metadata.get("audio_urls", [])
            is_ping = bool(m.msg_metadata.get("ping", False))
            curator_trigger = m.msg_metadata.get("curator_trigger")
        fb = feedbacks.get(m.id)
        run = ai_runs_by_msg.get(m.id)
        out.append(ChatMessageOut(
            id=m.id,
            role=m.role.value,
            text=m.text,
            created_at=m.created_at,
            need_curator=need_curator,
            curator_trigger=curator_trigger,
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
