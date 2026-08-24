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
    постгреса, на котором работает прод.

    NULL пропускаем как есть: постгрес на `lower(NULL)` отвечает NULL, а
    `str.lower(None)` роняет запрос целиком — на этом падал поиск клиента по
    имени, стоило в выборке оказаться клиенту без имени."""

    def _lower(value):
        return value.lower() if isinstance(value, str) else value

    @event.listens_for(engine.sync_engine, "connect")
    def _register(dbapi_connection, _record):
        dbapi_connection.create_function("lower", 1, _lower)


@pytest.fixture(autouse=True)
def no_vk_profile_lookup(monkeypatch):
    """Имя клиента из ВК в тестах не запрашиваем — сети в наборе быть не должно.

    Тест самого запроса подменяет vk_api_call и зовёт fetch_user_name напрямую.
    """
    async def _no_name(access_token, vk_user_id):
        return None, None

    monkeypatch.setattr("app.vk.sender.fetch_user_name", _no_name)


@pytest.fixture(autouse=True)
def no_max_network(monkeypatch):
    """Сети в наборе быть не должно — в том числе к MAX.

    Тесты, которым нужен ответ MAX, подменяют нужный вызов сами; эта заглушка
    ловит забытые пути, чтобы они падали внятно, а не висли на таймауте.
    """
    async def _no_network(*args, **kwargs):
        raise AssertionError("MAX API не должен вызываться в тестах")

    monkeypatch.setattr("app.max.client._request", _no_network)


@pytest.fixture(autouse=True)
def no_typing_grace(monkeypatch):
    """Пауза «не допишет ли клиент» в тестах нулевая.

    В проде она три секунды (см. webhook.CLIENT_TYPING_GRACE_SECONDS) и на живом
    трафике незаметна, а в наборе тестов складывалась в лишнюю минуту ожидания.
    Тест, который проверяет саму паузу, снимает эту подмену.
    """
    monkeypatch.setattr("app.vk.webhook.CLIENT_TYPING_GRACE_SECONDS", 0)


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
