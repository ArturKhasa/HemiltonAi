"""Ping rules CRUD API."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.models import PingRule, User
from app.db.session import get_db
from app.storage.rehost import rehost_external_photos

router = APIRouter(prefix="/ping-rules", tags=["ping-rules"])

# Temporary step value used while re-sequencing a group: the unique constraint
# (type_id, funnel_type, step, marketing_tag) forbids transient duplicates, so a rule
# being repositioned is parked on a negative step first, then the whole group is
# renumbered in a second pass.
_TEMP_STEP = -1_000_000


async def _group_rules(
    db: AsyncSession,
    type_id: int | None,
    funnel_type: str,
    marketing_tag: str | None,
    exclude_id: int | None = None,
) -> list[PingRule]:
    """All rules of one funnel group (type + funnel + tag), ordered by step."""
    q = (
        select(PingRule)
        .where(
            PingRule.type_id == type_id,
            PingRule.funnel_type == funnel_type,
            PingRule.marketing_tag == marketing_tag,
        )
        .order_by(PingRule.step, PingRule.id)
    )
    if exclude_id is not None:
        q = q.where(PingRule.id != exclude_id)
    return list((await db.execute(q)).scalars().all())


async def _apply_sequence(db: AsyncSession, rules: list[PingRule], base: int) -> None:
    """Assign consecutive steps base, base+1, ... preserving list order.

    Two-phase: rules that must move are parked on unique negative steps and flushed
    first, so the final assignment never trips the unique constraint mid-way.
    """
    changed = [(r, base + i) for i, r in enumerate(rules) if r.step != base + i]
    if not changed:
        return
    for i, (r, _) in enumerate(changed):
        r.step = -(i + 1)
    await db.flush()
    for r, target in changed:
        r.step = target
    await db.flush()


def _insert_position(requested_step: int, base: int, group_size: int) -> int:
    return max(0, min(requested_step - base, group_size))


class PingRuleOut(BaseModel):
    id: int
    type_id: int | None
    funnel_type: str
    step: int
    delay_seconds: int
    phrase_text: str
    manual_text: str | None
    after_status: str | None
    marketing_tag: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PingRuleCreateRequest(BaseModel):
    type_id: int | None = None
    funnel_type: str
    step: int
    delay_seconds: int
    phrase_text: str = ""
    manual_text: str | None = None
    after_status: str | None = None
    marketing_tag: str | None = None

    @model_validator(mode="after")
    def check_phrase_or_text(self):
        has_content = self.phrase_text.strip() or (self.manual_text and self.manual_text.strip())
        if not has_content and not self.after_status:
            raise ValueError("phrase_text, manual_text, or after_status is required")
        return self


class PingRuleUpdateRequest(BaseModel):
    funnel_type: str | None = None
    step: int | None = None
    delay_seconds: int | None = None
    phrase_text: str | None = None
    manual_text: str | None = None
    after_status: str | None = None
    marketing_tag: str | None = None
    is_active: bool | None = None


@router.get("/", response_model=list[PingRuleOut])
async def list_ping_rules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
    type_id: int | None = None,
    include_inactive: bool = False,
):
    q = select(PingRule)
    if not include_inactive:
        q = q.where(PingRule.is_active == True)
    if type_id is not None:
        q = q.where(PingRule.type_id == type_id)
    result = await db.execute(q.order_by(PingRule.funnel_type, PingRule.step))
    return result.scalars().all()


@router.post("/", response_model=PingRuleOut, status_code=201)
async def create_ping_rule(
    body: PingRuleCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    # Картинку по чужой ссылке забираем к себе сразу: ссылки на CDN ВК умирают
    # молча, и сообщение уходит без вложения (см. app.storage.rehost).
    rule = PingRule(
        type_id=body.type_id,
        funnel_type=body.funnel_type,
        step=_TEMP_STEP,
        delay_seconds=body.delay_seconds,
        phrase_text=await rehost_external_photos(body.phrase_text),
        manual_text=await rehost_external_photos(body.manual_text or "") or body.manual_text,
        after_status=body.after_status,
        marketing_tag=body.marketing_tag,
    )
    db.add(rule)
    await db.flush()
    # type_id=None is replaced by the column's server_default on insert — group by the
    # value actually stored, otherwise the new rule lands outside its own funnel group.
    await db.refresh(rule)

    group = await _group_rules(
        db, rule.type_id, body.funnel_type, body.marketing_tag, exclude_id=rule.id
    )
    if group:
        base = group[0].step
        pos = _insert_position(body.step, base, len(group))
    else:
        # Empty funnel: the requested step becomes the base, so funnels may start
        # at 0 or 1 — the worker picks up the first step by MIN.
        base = body.step
        pos = 0

    await _apply_sequence(db, group[:pos] + [rule] + group[pos:], base)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=PingRuleOut)
async def update_ping_rule(
    rule_id: int,
    body: PingRuleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    rule = await db.get(PingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Ping rule not found")

    updates = body.model_dump(exclude_unset=True)
    for _field in ("phrase_text", "manual_text"):
        if updates.get(_field):
            updates[_field] = await rehost_external_photos(updates[_field])

    new_phrase_text = updates.get("phrase_text", rule.phrase_text)
    new_manual_text = updates.get("manual_text", rule.manual_text)
    new_after_status = updates.get("after_status", rule.after_status)
    has_content = (new_phrase_text or "").strip() or (new_manual_text and new_manual_text.strip())
    if not has_content and not new_after_status:
        raise HTTPException(status_code=422, detail="phrase_text, manual_text, or after_status is required")

    new_step = updates.get("step", rule.step)
    new_funnel = updates.get("funnel_type", rule.funnel_type)
    new_marketing_tag = updates.get("marketing_tag", rule.marketing_tag)
    group_changed = new_funnel != rule.funnel_type or new_marketing_tag != rule.marketing_tag
    step_changed = new_step != rule.step

    old_funnel, old_tag = rule.funnel_type, rule.marketing_tag
    old_group = await _group_rules(db, rule.type_id, old_funnel, old_tag)
    old_base = old_group[0].step if old_group else 0

    for k, v in updates.items():
        if k != "step":
            setattr(rule, k, v)

    if group_changed:
        rest = [r for r in old_group if r.id != rule.id]
        target_group = await _group_rules(
            db, rule.type_id, new_funnel, new_marketing_tag, exclude_id=rule.id
        )
        target_base = target_group[0].step if target_group else new_step
        pos = _insert_position(new_step, target_base, len(target_group))
        rule.step = _TEMP_STEP
        await db.flush()
        await _apply_sequence(db, rest, old_base)
        await _apply_sequence(db, target_group[:pos] + [rule] + target_group[pos:], target_base)
    elif step_changed:
        others = [r for r in old_group if r.id != rule.id]
        pos = _insert_position(new_step, old_base, len(others))
        rule.step = _TEMP_STEP
        await db.flush()
        await _apply_sequence(db, others[:pos] + [rule] + others[pos:], old_base)

    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_ping_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    rule = await db.get(PingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Ping rule not found")
    group = await _group_rules(db, rule.type_id, rule.funnel_type, rule.marketing_tag)
    # Base is the group's min step INCLUDING the deleted rule: deleting the first
    # step of 0,1,2 collapses to 0,1 (not 1,2), preserving the funnel's start.
    base = group[0].step if group else 0
    rest = [r for r in group if r.id != rule.id]
    await db.delete(rule)
    await db.flush()
    await _apply_sequence(db, rest, base)
    await db.commit()
