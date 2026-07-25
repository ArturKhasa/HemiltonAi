"""add dialog_example_embeddings (pgvector) — семантический поиск похожих Q&A

Revision ID: 040
Revises: 039
Create Date: 2026-07-24

Пары (реплика клиента → ответ менеджера), извлечённые из реальных диалогов, с
эмбеддингом client_text для инструмента find_similar_examples — RAG поверх
исторических переписок вместо жёстких скриптов.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "dialog_example_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("dialog_types.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_text", sa.Text(), nullable=False),
        sa.Column("manager_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    # HNSW по косинусному расстоянию — быстрый ANN-поиск для find_similar_examples.
    op.execute(
        "CREATE INDEX ix_dialog_example_embeddings_hnsw ON dialog_example_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_index(
        "ix_dialog_example_embeddings_type", "dialog_example_embeddings", ["type_id"],
    )


def downgrade() -> None:
    op.drop_table("dialog_example_embeddings")
