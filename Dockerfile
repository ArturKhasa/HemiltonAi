FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
WORKDIR /app

ENV PYTHONPATH=/app

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system --no-build-isolation \
    fastapi uvicorn[standard] sqlalchemy[asyncio] alembic asyncpg \
    pydantic[email] pydantic-settings bcrypt python-jose[cryptography] \
    openai-agents litellm openai anthropic tiktoken \
    python-multipart websockets pgvector

COPY . .
COPY --from=frontend-build /frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["sh", "-c", "\
  echo '[startup] Running migrations...' && \
  until alembic upgrade head; do \
    echo '[startup] DB not ready or migration failed, retrying in 3s...'; \
    sleep 3; \
  done && \
  echo '[startup] Migrations OK. Running seed...' && \
  python -m app.commands.seed && \
  echo '[startup] Starting uvicorn...' && \
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
