from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

# Ping due-send holds up to PING_DUE_CONCURRENCY connections for whole LLM round-trips
# (minutes each); pool must leave headroom for API traffic on top of that.
#
# statement_cache_size=0 — DATABASE_URL may point through pgbouncer in transaction/
# statement pooling mode (no sticky server connection per client), which doesn't
# support asyncpg's server-side prepared statements: a statement prepared on one
# pooled connection can vanish before a later query on the "same" client connection
# reuses it, raising InvalidSQLStatementNameError at random. Disabling the cache costs
# a little latency but is required for correctness behind such a pooler; harmless
# against a direct (non-pgbouncer) Postgres connection too.
engine = create_async_engine(
    settings.DATABASE_URL, echo=False, pool_size=10, max_overflow=20,
    connect_args={"statement_cache_size": 0},
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
