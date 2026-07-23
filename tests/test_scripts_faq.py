import pytest
from sqlalchemy import insert

from app.db.models import Script
from app.sales.scripts import ScriptService


@pytest.fixture
async def script_service(db):
    await db.execute(
        insert(Script).values([
            {"condition": "intro", "phrase_text": "Привет! {Чем|Как} могу помочь?", "is_active": True},
            {"condition": "price objection", "phrase_text": "Понимаю, давайте подберём вариант", "is_active": True},
            {"condition": "old", "phrase_text": "устаревший текст", "is_active": False},
        ])
    )
    await db.commit()
    return ScriptService(db)


async def test_get_active_scripts_excludes_inactive(script_service):
    scripts = await script_service.get_all_active()
    assert len(scripts) == 2
    conditions = [s.condition for s in scripts]
    assert "old" not in conditions
