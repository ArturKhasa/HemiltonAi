"""Семантический поиск похожих Q&A из реальных диалогов (RAG поверх переписок,
не жёсткий скрипт) — эмбеддинг client_text через OpenAI, поиск по pgvector."""
import logging

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import DialogExampleEmbedding

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """До ~2048 текстов за раз (лимит OpenAI embeddings API на batch)."""
    client = _get_client()
    resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


async def embed_text(text: str) -> list[float]:
    return (await embed_texts([text]))[0]


async def find_similar(
    db: AsyncSession, type_id: int, query: str, limit: int = 3,
) -> list[DialogExampleEmbedding]:
    query_vec = await embed_text(query)
    result = await db.execute(
        select(DialogExampleEmbedding)
        .where(DialogExampleEmbedding.type_id == type_id)
        .order_by(DialogExampleEmbedding.embedding.cosine_distance(query_vec))
        .limit(limit)
    )
    return list(result.scalars().all())
