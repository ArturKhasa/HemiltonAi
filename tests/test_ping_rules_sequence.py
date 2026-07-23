"""Ping-rule step sequencing: create inserts with shift, delete renumbers,
funnels may start at 0 or 1."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.ping_rules import (
    PingRuleCreateRequest,
    PingRuleUpdateRequest,
    create_ping_rule,
    delete_ping_rule,
    update_ping_rule,
)
from app.db.models import PingRule


@pytest.fixture
async def db():
    """Own fixture: the shared one creates ALL tables, and clients.marketing_tags
    (JSONB) does not compile on SQLite. Ping-rule sequencing only needs ping_rules."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: PingRule.__table__.create(c))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _steps(db, funnel="regular", tag=None):
    result = await db.execute(
        select(PingRule)
        .where(PingRule.funnel_type == funnel, PingRule.marketing_tag == tag)
        .order_by(PingRule.step)
    )
    return [(r.step, r.id) for r in result.scalars().all()]


def _req(step, funnel="regular", tag=None, text="txt"):
    return PingRuleCreateRequest(
        funnel_type=funnel, step=step, delay_seconds=60, manual_text=text, marketing_tag=tag,
    )


@pytest.mark.asyncio
async def test_create_appends_and_inserts_with_shift(db):
    r0 = await create_ping_rule(_req(0), db, None)
    r1 = await create_ping_rule(_req(1), db, None)
    r2 = await create_ping_rule(_req(2), db, None)
    assert [s for s, _ in await _steps(db)] == [0, 1, 2]

    # Insert at occupied step 1 → old 1 and 2 shift up.
    r_new = await create_ping_rule(_req(1), db, None)
    steps = await _steps(db)
    assert [s for s, _ in steps] == [0, 1, 2, 3]
    assert steps[1][1] == r_new.id
    assert steps[2][1] == r1.id
    assert steps[3][1] == r2.id
    assert steps[0][1] == r0.id

    # Step far beyond the end is clamped to append, no gap.
    r_far = await create_ping_rule(_req(99), db, None)
    steps = await _steps(db)
    assert [s for s, _ in steps] == [0, 1, 2, 3, 4]
    assert steps[-1][1] == r_far.id


@pytest.mark.asyncio
async def test_delete_renumbers_remaining(db):
    rules = [await create_ping_rule(_req(i), db, None) for i in range(4)]
    await delete_ping_rule(rules[1].id, db, None)
    steps = await _steps(db)
    assert [s for s, _ in steps] == [0, 1, 2]
    assert [rid for _, rid in steps] == [rules[0].id, rules[2].id, rules[3].id]

    # Deleting the first step keeps the funnel base (0).
    await delete_ping_rule(rules[0].id, db, None)
    steps = await _steps(db)
    assert [s for s, _ in steps] == [0, 1]
    assert [rid for _, rid in steps] == [rules[2].id, rules[3].id]


@pytest.mark.asyncio
async def test_funnel_starting_at_one(db):
    await create_ping_rule(_req(1), db, None)
    await create_ping_rule(_req(2), db, None)
    r3 = await create_ping_rule(_req(5), db, None)  # clamped to append at 3
    assert [s for s, _ in await _steps(db)] == [1, 2, 3]

    await delete_ping_rule(r3.id, db, None)
    assert [s for s, _ in await _steps(db)] == [1, 2]


@pytest.mark.asyncio
async def test_update_moves_step_within_group(db):
    rules = [await create_ping_rule(_req(i), db, None) for i in range(4)]
    # Move step 3 to position 1 → everything between shifts down.
    await update_ping_rule(rules[3].id, PingRuleUpdateRequest(step=1), db, None)
    steps = await _steps(db)
    assert [s for s, _ in steps] == [0, 1, 2, 3]
    assert [rid for _, rid in steps] == [rules[0].id, rules[3].id, rules[1].id, rules[2].id]

    # Move step 1 down to 3.
    await update_ping_rule(rules[3].id, PingRuleUpdateRequest(step=3), db, None)
    steps = await _steps(db)
    assert [rid for _, rid in steps] == [rules[0].id, rules[1].id, rules[2].id, rules[3].id]


@pytest.mark.asyncio
async def test_update_moves_between_funnels(db):
    a = [await create_ping_rule(_req(i, funnel="a"), db, None) for i in range(3)]
    b = [await create_ping_rule(_req(i, funnel="b"), db, None) for i in range(2)]

    await update_ping_rule(a[0].id, PingRuleUpdateRequest(funnel_type="b", step=1), db, None)

    steps_a = await _steps(db, funnel="a")
    assert [s for s, _ in steps_a] == [0, 1]
    assert [rid for _, rid in steps_a] == [a[1].id, a[2].id]

    steps_b = await _steps(db, funnel="b")
    assert [s for s, _ in steps_b] == [0, 1, 2]
    assert [rid for _, rid in steps_b] == [b[0].id, a[0].id, b[1].id]


@pytest.mark.asyncio
async def test_tag_groups_are_independent(db):
    await create_ping_rule(_req(0), db, None)
    await create_ping_rule(_req(0, tag="#X"), db, None)
    await create_ping_rule(_req(0, tag="#X"), db, None)  # insert at 0, shifts tagged only
    assert [s for s, _ in await _steps(db)] == [0]
    assert [s for s, _ in await _steps(db, tag="#X")] == [0, 1]
