"""Admin API — user management, AI cost metrics."""
from datetime import date, datetime, timedelta

from app.utils.time import msk_now

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.auth.service import hash_password
from app.config import settings
from app.db.models import AIRun, Dialog, DialogType, User, UserDialogType, UserRole
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


class UserOut(BaseModel):
    id: int
    email: str
    # Имя менеджера: им подписан ответственный за диалог в списке лидов.
    name: str | None = None
    role: str
    created_at: datetime
    dialog_type_ids: list[int] = []

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None
    role: str = "curator"
    dialog_type_ids: list[int] | None = None


class UpdateUserRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    password: str | None = None
    dialog_type_ids: list[int] | None = None


class MetricsOut(BaseModel):
    period_days: int
    total_ai_runs: int
    total_cost_usd: float
    total_tokens: int
    avg_confidence: float | None
    curator_triggered_count: int
    curator_trigger_rate: float


class SpendingSeries(BaseModel):
    type_id: int | None
    display_name: str
    total_cost_usd: float
    total_runs: int
    total_dialogs: int
    avg_cost_per_dialog: float
    cost_usd: list[float]        # aligned to `dates`
    runs: list[int]             # aligned to `dates`
    dialogs: list[int]          # distinct dialogs per day
    cost_per_dialog: list[float]  # cost_usd / dialogs per day


# Cost data before this date is known-skewed (openai ping billed cache at full
# price, qwen cache multiplier was 0.13 vs the real 0.2, failed runs weren't
# recorded) — /admin/spending clamps its period here.
SPENDING_DATA_FLOOR = date(2026, 7, 14)


class SpendingByTypeOut(BaseModel):
    period_days: int
    date_basis: str          # "run" | "dialog"
    provider: str            # "all" | ai_runs.provider value the series are filtered to
    segment: str             # "all" | dialogs.ai_provider — the A/B arm (qwen arm includes its openai pings)
    tax_rate: float          # estimated tax applied to costs (0.20 = +20%)
    dates: list[str]
    series: list[SpendingSeries]


async def _user_type_ids(db: AsyncSession, user_ids: list[int]) -> dict[int, list[int]]:
    """user_id -> отсортированный список привязанных type_id."""
    if not user_ids:
        return {}
    result = await db.execute(
        select(UserDialogType.user_id, UserDialogType.type_id)
        .where(UserDialogType.user_id.in_(user_ids))
        .order_by(UserDialogType.type_id)
    )
    mapping: dict[int, list[int]] = {}
    for uid, tid in result.all():
        mapping.setdefault(uid, []).append(tid)
    return mapping


async def _set_user_type_ids(db: AsyncSession, user_id: int, type_ids: list[int]) -> None:
    """Полностью заменить набор направлений пользователя. Неизвестные id отбрасываются."""
    valid_result = await db.execute(select(DialogType.id).where(DialogType.id.in_(type_ids)))
    valid_ids = set(valid_result.scalars().all())
    await db.execute(
        UserDialogType.__table__.delete().where(UserDialogType.user_id == user_id)
    )
    for tid in sorted(valid_ids):
        db.add(UserDialogType(user_id=user_id, type_id=tid))


def _user_out(user: User, type_ids: list[int]) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role.value,
        created_at=user.created_at,
        dialog_type_ids=type_ids,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    mapping = await _user_type_ids(db, [u.id for u in users])
    return [_user_out(u, mapping.get(u.id, [])) for u in users]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=(body.name or "").strip() or None,
        role=role,
    )
    db.add(user)
    await db.flush()
    if body.dialog_type_ids:
        await _set_user_type_ids(db, user.id, body.dialog_type_ids)
    await db.commit()
    await db.refresh(user)
    mapping = await _user_type_ids(db, [user.id])
    return _user_out(user, mapping.get(user.id, []))


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.name is not None:
        # Пустая строка — снять имя, снова показывать адрес.
        user.name = body.name.strip() or None

    if body.role is not None:
        try:
            user.role = UserRole(body.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")

    if body.password is not None:
        user.password_hash = hash_password(body.password)

    if body.dialog_type_ids is not None:
        await _set_user_type_ids(db, user.id, body.dialog_type_ids)

    user.updated_at = msk_now()
    await db.commit()
    await db.refresh(user)
    mapping = await _user_type_ids(db, [user.id])
    return _user_out(user, mapping.get(user.id, []))


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()


@router.get("/metrics", response_model=MetricsOut)
async def get_metrics(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    since = msk_now() - timedelta(days=days)
    result = await db.execute(
        select(
            func.count(AIRun.id),
            func.coalesce(func.sum(AIRun.cost_amount), 0),
            func.coalesce(func.sum(AIRun.total_tokens), 0),
            func.avg(AIRun.confidence_score),
        ).where(AIRun.created_at >= since)
    )
    row = result.one()
    total_runs, total_cost, total_tokens, avg_conf = row

    curator_result = await db.execute(
        select(func.count(AIRun.id)).where(
            AIRun.created_at >= since,
            AIRun.need_curator == True,
        )
    )
    curator_count = curator_result.scalar() or 0
    curator_rate = curator_count / total_runs if total_runs else 0.0

    return MetricsOut(
        period_days=days,
        total_ai_runs=total_runs,
        total_cost_usd=float(total_cost or 0),
        total_tokens=int(total_tokens or 0),
        avg_confidence=float(avg_conf) if avg_conf is not None else None,
        curator_triggered_count=curator_count,
        curator_trigger_rate=round(curator_rate, 4),
    )


@router.get("/spending-by-type", response_model=SpendingByTypeOut)
async def spending_by_type(
    days: int = 30,
    date_basis: str = "run",  # "run" = ai_runs.created_at, "dialog" = dialogs.created_at
    provider: str = "all",    # "all" | "openai" | "qwen" | "anthropic" | "minimax"
    segment: str = "all",     # "all" | dialogs.ai_provider — A/B arm incl. all its runs
    end: str | None = None,   # ISO date the period ends on (inclusive); default today
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """Daily AI spending (cost_amount) grouped by dialog_type direction."""
    days = max(1, min(days, 365))
    if provider not in ("openai", "qwen", "anthropic", "minimax"):
        provider = "all"
    provider_filter = [AIRun.provider == provider] if provider != "all" else []
    # Segment = the dialog's A/B arm. Unlike the provider filter (which slices by
    # who billed the run), the qwen arm keeps its openai ping runs — full arm cost.
    if segment not in ("openai", "qwen"):
        segment = "all"
    if segment != "all":
        provider_filter.append(Dialog.ai_provider == segment)
    tax_mult = 1.0 + max(0.0, settings.ESTIMATED_TAX_RATE)
    # Which timestamp anchors the day bucket / period filter.
    date_src = Dialog.created_at if date_basis == "dialog" else AIRun.created_at
    today = msk_now().date()
    end_date = today
    if end:
        try:
            end_date = min(date.fromisoformat(end), today)
        except ValueError:
            pass
    start = end_date - timedelta(days=days - 1)
    # Cost accounting was fixed on 2026-07-14 (prompt-cache rates, failed-run
    # usage); earlier cost_amount values are known-skewed, so the page never
    # shows them to avoid mixing incomparable numbers.
    if end_date < SPENDING_DATA_FLOOR:
        # The whole requested period predates reliable data — nothing to show.
        return SpendingByTypeOut(
            period_days=0,
            date_basis="dialog" if date_basis == "dialog" else "run",
            provider=provider,
            segment=segment,
            tax_rate=settings.ESTIMATED_TAX_RATE,
            dates=[],
            series=[],
        )
    start = max(start, SPENDING_DATA_FLOOR)
    days = (end_date - start).days + 1
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    dates = [(start + timedelta(days=i)) for i in range(days)]
    date_index = {d: i for i, d in enumerate(dates)}

    day_col = cast(date_src, Date).label("day")
    result = await db.execute(
        select(
            day_col,
            Dialog.type_id,
            DialogType.display_name,
            func.coalesce(func.sum(AIRun.cost_amount), 0),
            func.count(AIRun.id),
            func.count(func.distinct(AIRun.dialog_id)),
        )
        .join(Dialog, AIRun.dialog_id == Dialog.id)
        .outerjoin(DialogType, Dialog.type_id == DialogType.id)
        .where(date_src >= start_dt, date_src < end_dt, *provider_filter)
        .group_by(day_col, Dialog.type_id, DialogType.display_name)
        .order_by(day_col)
    )

    # type_id -> {"display_name", "cost":[...], "runs":[...], "dialogs":[...]}
    buckets: dict[int | None, dict] = {}
    for day, type_id, display_name, cost, runs, dialogs in result.all():
        b = buckets.get(type_id)
        if b is None:
            b = {
                "display_name": display_name or "Без типа",
                "cost": [0.0] * days,
                "runs": [0] * days,
                "dialogs": [0] * days,
            }
            buckets[type_id] = b
        idx = date_index.get(day)
        if idx is None:
            continue
        b["cost"][idx] = float(cost or 0) * tax_mult
        b["runs"][idx] = int(runs or 0)
        b["dialogs"][idx] = int(dialogs or 0)

    # Distinct dialogs over the WHOLE period per type — a dialog active on
    # several days must count once, not once per day (otherwise the period
    # avg-cost-per-dialog divides by an inflated dialog count).
    period_q = await db.execute(
        select(
            Dialog.type_id,
            func.count(func.distinct(AIRun.dialog_id)),
        )
        .join(Dialog, AIRun.dialog_id == Dialog.id)
        .where(date_src >= start_dt, date_src < end_dt, *provider_filter)
        .group_by(Dialog.type_id)
    )
    period_dialogs = {type_id: int(cnt or 0) for type_id, cnt in period_q.all()}

    series = []
    for type_id, b in buckets.items():
        cost_per_dialog = [
            round(c / d, 6) if d else 0.0 for c, d in zip(b["cost"], b["dialogs"])
        ]
        total_cost = sum(b["cost"])
        total_dialogs = period_dialogs.get(type_id, 0)
        series.append(
            SpendingSeries(
                type_id=type_id,
                display_name=b["display_name"],
                total_cost_usd=round(total_cost, 6),
                total_runs=sum(b["runs"]),
                total_dialogs=total_dialogs,
                avg_cost_per_dialog=round(total_cost / total_dialogs, 6) if total_dialogs else 0.0,
                cost_usd=[round(c, 6) for c in b["cost"]],
                runs=b["runs"],
                dialogs=b["dialogs"],
                cost_per_dialog=cost_per_dialog,
            )
        )
    series.sort(key=lambda s: s.total_cost_usd, reverse=True)

    return SpendingByTypeOut(
        period_days=days,
        date_basis="dialog" if date_basis == "dialog" else "run",
        provider=provider,
        segment=segment,
        tax_rate=settings.ESTIMATED_TAX_RATE,
        dates=[d.isoformat() for d in dates],
        series=series,
    )


