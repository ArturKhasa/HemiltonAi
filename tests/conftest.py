import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.db.models import Base
from app.db.session import get_db

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


def _use_unicode_lower(engine) -> None:
    """SQLite'овский lower() знает только ASCII, поэтому «Черный» остался бы
    «Черный» и поиск по товарам вёл бы себя в тестах не так, как в проде.
    Подменяем на питоновский str.lower — он совпадает с юникодным lower()
    постгреса, на котором работает прод."""

    @event.listens_for(engine.sync_engine, "connect")
    def _register(dbapi_connection, _record):
        dbapi_connection.create_function("lower", 1, str.lower)


@pytest.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL)
    _use_unicode_lower(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
