import pytest
from sqlalchemy import text


async def test_tables_exist(db):
    result = await db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    tables = {row[0] for row in result}
    expected = {
        "users", "clients", "dialogs", "messages", "ai_runs",
        "scripts", "prompt_versions",
    }
    assert expected.issubset(tables)
