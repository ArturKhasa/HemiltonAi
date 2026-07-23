from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

# Ping due-send holds up to PING_DUE_CONCURRENCY connections for whole LLM round-trips
# (minutes each); pool must leave headroom for API traffic on top of that.
engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
