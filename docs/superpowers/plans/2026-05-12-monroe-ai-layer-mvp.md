# Monro AI Layer — MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI sales agent service for Monroe Art photobooks — accepts CRM messages, generates structured AI responses via openai-agents SDK, provides curator review + tester chat UI.

**Architecture:** Single FastAPI monolith serves JSON API + Vue 3 SPA static files. openai-agents SDK orchestrates SalesAgent and ObjectionAgent. LiteLLMModel adapter enables OpenAI and Anthropic interchangeably. PostgreSQL stores all state. Default mode: `draft_only` — AI proposes, curator approves.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2.x async, Alembic, openai-agents, litellm, Pydantic v2, pydantic-settings, passlib[bcrypt], python-jose, Vue 3 + Vite + Pinia + Vue Router 4 + Axios + TailwindCSS, PostgreSQL 16, pytest + pytest-asyncio + httpx

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `alembic.ini`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/main.py`
- Create: `app/db/__init__.py`
- Create: `app/db/session.py`
- Create: `app/auth/__init__.py`
- Create: `app/crm/__init__.py`
- Create: `app/ai/__init__.py`
- Create: `app/sales/__init__.py`
- Create: `app/curator/__init__.py`
- Create: `app/api/__init__.py`
- Create: `app/commands/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "monroe-ai-layer"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0",
    "alembic>=1.13",
    "asyncpg>=0.29",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "passlib[bcrypt]>=1.7",
    "python-jose[cryptography]>=3.3",
    "openai-agents>=0.0.7",
    "litellm>=1.40",
    "openai>=1.30",
    "anthropic>=0.25",
    "tiktoken>=0.7",
    "python-multipart>=0.0.9",
    "websockets>=12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "aiosqlite>=0.20",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system -e .

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: monroe
      POSTGRES_USER: monroe
      POSTGRES_PASSWORD: monroe
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  app:
    build: .
    depends_on:
      - db
    ports:
      - "8000:8000"
    env_file: .env
    volumes:
      - ./frontend/dist:/app/frontend/dist

volumes:
  postgres_data:
```

- [ ] **Step 4: Create `.env.example`**

```env
DATABASE_URL=postgresql+asyncpg://monroe:monroe@localhost:5432/monroe
SECRET_KEY=change-me-in-production-use-32-random-chars
ACCESS_TOKEN_EXPIRE_MINUTES=10080

OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
AI_PROVIDER=openai
MODEL_NAME=gpt-4o
AI_SEND_MODE=draft_only
CONFIDENCE_THRESHOLD=0.72
```

- [ ] **Step 5: Create `alembic.ini`**

```ini
[alembic]
script_location = app/db/migrations
sqlalchemy.url = postgresql+asyncpg://monroe:monroe@localhost:5432/monroe

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 6: Create `app/config.py`**

```python
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://monroe:monroe@localhost:5432/monroe"
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080

    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    AI_PROVIDER: str = "openai"
    MODEL_NAME: str = "gpt-4o"
    AI_SEND_MODE: str = "draft_only"
    CONFIDENCE_THRESHOLD: float = 0.72

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

- [ ] **Step 7: Create `app/db/session.py`**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 8: Create `app/main.py` (stub — routers added in later tasks)**

```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Monro AI Layer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers registered in later tasks

frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")
```

- [ ] **Step 9: Create empty `__init__.py` files**

```bash
touch app/__init__.py app/auth/__init__.py app/crm/__init__.py app/ai/__init__.py \
      app/sales/__init__.py app/curator/__init__.py app/api/__init__.py \
      app/commands/__init__.py app/db/__init__.py tests/__init__.py
```

- [ ] **Step 10: Create `tests/conftest.py`**

```python
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.db.models import Base
from app.db.session import get_db

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL)
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
```

- [ ] **Step 11: Verify scaffold runs**

```bash
uv pip install -e ".[dev]"
python -c "from app.config import settings; print(settings.AI_PROVIDER)"
```

Expected output: `openai`

- [ ] **Step 12: Commit**

```bash
git init
git add .
git commit -m "feat: project scaffold — FastAPI, config, Docker, pytest setup"
```

---

### Task 2: Database models + Alembic

**Files:**
- Create: `app/db/models.py`
- Create: `app/db/migrations/env.py`
- Create: `app/db/migrations/script.py.mako`
- Create: `app/db/migrations/versions/001_initial_schema.py`

- [ ] **Step 1: Create `app/db/models.py`**

```python
import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Column, DateTime, Enum as SAEnum, ForeignKey,
    Integer, Numeric, String, Text, JSON, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class UserRole(enum.Enum):
    admin = "admin"
    curator = "curator"
    tester = "tester"


class MessageRole(enum.Enum):
    client = "client"
    ai = "ai"
    curator = "curator"
    system = "system"


class DialogStatus(enum.Enum):
    interested = "interested"
    calculated = "calculated"
    hot = "hot"
    waiting_prepayment = "waiting_prepayment"
    order_created = "order_created"
    needs_curator = "needs_curator"
    lost = "lost"
    no_response = "no_response"
    spam = "spam"
    test = "test"


class ReviewStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    edited = "edited"
    rejected = "rejected"
    takeover = "takeover"


class DialogExampleLabel(enum.Enum):
    success = "success"
    fail = "fail"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.tester)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    crm_client_id = Column(String(255), unique=True, nullable=True)
    name = Column(String(255), nullable=True)
    source = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Dialog(Base):
    __tablename__ = "dialogs"
    id = Column(Integer, primary_key=True)
    crm_dialog_id = Column(String(255), unique=True, nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    current_status = Column(SAEnum(DialogStatus), nullable=False, default=DialogStatus.interested)
    assigned_curator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_test = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_message_at = Column(DateTime, nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    dialog_id = Column(Integer, ForeignKey("dialogs.id"), nullable=False)
    role = Column(SAEnum(MessageRole), nullable=False)
    text = Column(Text, nullable=False)
    external_message_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    msg_metadata = Column("metadata", JSON, nullable=True)


class StatusHistory(Base):
    __tablename__ = "status_history"
    id = Column(Integer, primary_key=True)
    dialog_id = Column(Integer, ForeignKey("dialogs.id"), nullable=False)
    old_status = Column(String(64), nullable=True)
    new_status = Column(String(64), nullable=False)
    reason = Column(Text, nullable=True)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AIRun(Base):
    __tablename__ = "ai_runs"
    id = Column(Integer, primary_key=True)
    dialog_id = Column(Integer, ForeignKey("dialogs.id"), nullable=False)
    input_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    output_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    provider = Column(String(64), nullable=False)
    model = Column(String(128), nullable=False)
    prompt_version = Column(String(64), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    cost_amount = Column(Numeric(12, 6), nullable=True)
    cost_currency = Column(String(8), default="USD")
    cost_estimated = Column(Boolean, default=False)
    latency_ms = Column(Integer, nullable=True)
    confidence_score = Column(Numeric(4, 3), nullable=True)
    need_curator = Column(Boolean, default=False)
    curator_reason = Column(Text, nullable=True)
    selected_script = Column(String(255), nullable=True)
    status_before = Column(String(64), nullable=True)
    status_after = Column(String(64), nullable=True)
    raw_response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ModelPricing(Base):
    __tablename__ = "model_pricing"
    id = Column(Integer, primary_key=True)
    provider = Column(String(64), nullable=False)
    model = Column(String(128), nullable=False)
    input_price_per_1m = Column(Numeric(10, 4), nullable=False)
    output_price_per_1m = Column(Numeric(10, 4), nullable=False)
    currency = Column(String(8), default="USD")
    valid_from = Column(DateTime, nullable=True)
    valid_to = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)


class PriceLadder(Base):
    __tablename__ = "price_ladder"
    id = Column(Integer, primary_key=True)
    product_type = Column(String(64), default="photobook")
    size = Column(String(16), nullable=False)
    spreads_count = Column(Integer, nullable=False)
    regular_price = Column(Numeric(10, 2), nullable=False)
    minimum_price = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(8), default="RUB")
    is_active = Column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("product_type", "size", "spreads_count"),)


class Script(Base):
    __tablename__ = "scripts"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    category = Column(String(64), nullable=True)
    stage = Column(String(64), nullable=True)
    objection_type = Column(String(64), nullable=True)
    body = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FAQ(Base):
    __tablename__ = "faq"
    id = Column(Integer, primary_key=True)
    key = Column(String(128), nullable=False, unique=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CuratorReview(Base):
    __tablename__ = "curator_reviews"
    id = Column(Integer, primary_key=True)
    dialog_id = Column(Integer, ForeignKey("dialogs.id"), nullable=False)
    ai_run_id = Column(Integer, ForeignKey("ai_runs.id"), nullable=True)
    status = Column(SAEnum(ReviewStatus), nullable=False, default=ReviewStatus.pending)
    ai_draft = Column(Text, nullable=True)
    final_text = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    curator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    version = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("name", "version"),)


class DialogExample(Base):
    __tablename__ = "dialog_examples"
    id = Column(Integer, primary_key=True)
    crm_dialog_id = Column(String(255), nullable=False)
    label = Column(SAEnum(DialogExampleLabel), nullable=False)
    imported_at = Column(DateTime, default=datetime.utcnow)
    analyzed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    conversion_stage = Column(String(64), nullable=True)
    failure_reason = Column(Text, nullable=True)
    success_pattern = Column(Text, nullable=True)
```

- [ ] **Step 2: Initialize Alembic**

```bash
mkdir -p app/db/migrations/versions
alembic init app/db/migrations
```

- [ ] **Step 3: Replace `app/db/migrations/env.py`**

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    import os
    from app.config import settings

    url = os.environ.get("DATABASE_URL", settings.DATABASE_URL)
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


run_migrations_online()
```

- [ ] **Step 4: Create `app/db/migrations/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 5: Generate + apply first migration**

```bash
alembic revision --autogenerate -m "initial_schema"
alembic upgrade head
```

Expected: all 13 tables created in PostgreSQL.

- [ ] **Step 6: Write model import test**

```python
# tests/test_models.py
import pytest
from sqlalchemy import text


async def test_tables_exist(db):
    result = await db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    tables = {row[0] for row in result}
    expected = {
        "users", "clients", "dialogs", "messages", "ai_runs",
        "model_pricing", "price_ladder", "scripts", "faq",
        "curator_reviews", "prompt_versions", "dialog_examples", "status_history",
    }
    assert expected.issubset(tables)
```

- [ ] **Step 7: Run test**

```bash
pytest tests/test_models.py -v
```

Expected: `PASSED`

- [ ] **Step 8: Commit**

```bash
git add app/db/ alembic.ini tests/test_models.py
git commit -m "feat: database models and Alembic migrations"
```

---

### Task 3: Auth — register / login / JWT

**Files:**
- Create: `app/auth/service.py`
- Create: `app/auth/dependencies.py`
- Create: `app/auth/router.py`
- Modify: `app/main.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing auth tests**

```python
# tests/test_auth.py
import pytest


async def test_register_creates_user(client):
    resp = await client.post("/auth/register", json={
        "email": "test@monroe.ru",
        "password": "secret123",
        "role": "tester",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@monroe.ru"
    assert data["role"] == "tester"
    assert "password_hash" not in data


async def test_login_returns_token(client):
    await client.post("/auth/register", json={
        "email": "login@monroe.ru",
        "password": "secret123",
        "role": "tester",
    })
    resp = await client.post("/auth/login", json={
        "email": "login@monroe.ru",
        "password": "secret123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client):
    await client.post("/auth/register", json={
        "email": "bad@monroe.ru",
        "password": "secret123",
        "role": "tester",
    })
    resp = await client.post("/auth/login", json={
        "email": "bad@monroe.ru",
        "password": "wrong",
    })
    assert resp.status_code == 401


async def test_me_requires_auth(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_returns_user(client):
    await client.post("/auth/register", json={
        "email": "me@monroe.ru",
        "password": "secret123",
        "role": "curator",
    })
    login = await client.post("/auth/login", json={
        "email": "me@monroe.ru",
        "password": "secret123",
    })
    token = login.json()["access_token"]
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@monroe.ru"
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/test_auth.py -v
```

Expected: `ERROR` — routes not found.

- [ ] **Step 3: Create `app/auth/service.py`**

```python
from datetime import datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire},
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
```

- [ ] **Step 4: Create `app/auth/dependencies.py`**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import decode_token
from app.db.models import User, UserRole
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise exc
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise exc
    return user


def require_role(*roles: UserRole):
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return checker
```

- [ ] **Step 5: Create `app/auth/router.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.service import create_access_token, hash_password, verify_password
from app.db.models import User, UserRole
from app.db.session import get_db

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = "tester"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    role: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=UserResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    try:
        role = UserRole[body.role]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")
    user = User(email=body.email, password_hash=hash_password(body.password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse(id=user.id, email=user.email, role=user.role.value)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse(id=current_user.id, email=current_user.email, role=current_user.role.value)
```

- [ ] **Step 6: Register router in `app/main.py`**

```python
# Add after existing imports:
from app.auth.router import router as auth_router

# Add after middleware:
app.include_router(auth_router, prefix="/auth", tags=["auth"])
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_auth.py -v
```

Expected: all 5 PASSED.

- [ ] **Step 8: Commit**

```bash
git add app/auth/ app/main.py tests/test_auth.py
git commit -m "feat: auth — register, login, JWT, role-based dependency"
```

---

### Task 4: Pricing domain

**Files:**
- Create: `app/sales/statuses.py`
- Create: `app/sales/pricing.py`
- Create: `tests/test_pricing.py`

- [ ] **Step 1: Write failing pricing tests**

```python
# tests/test_pricing.py
import pytest
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PriceLadder
from app.sales.pricing import calculate_price, PriceType


async def _seed_prices(db: AsyncSession):
    rows = [
        PriceLadder(size="15x15", spreads_count=10, regular_price=Decimal("7570"), minimum_price=Decimal("7000")),
        PriceLadder(size="20x20", spreads_count=10, regular_price=Decimal("9400"), minimum_price=Decimal("8670")),
        PriceLadder(size="25x25", spreads_count=10, regular_price=Decimal("13600"), minimum_price=Decimal("12900")),
        PriceLadder(size="30x30", spreads_count=10, regular_price=Decimal("16700"), minimum_price=Decimal("15800")),
        PriceLadder(size="15x15", spreads_count=5, regular_price=Decimal("5400"), minimum_price=Decimal("4600")),
        PriceLadder(size="20x20", spreads_count=5, regular_price=Decimal("7122"), minimum_price=Decimal("5910")),
        PriceLadder(size="25x25", spreads_count=5, regular_price=Decimal("8700"), minimum_price=Decimal("8100")),
        PriceLadder(size="30x30", spreads_count=5, regular_price=Decimal("10300"), minimum_price=Decimal("9700")),
    ]
    for row in rows:
        db.add(row)
    await db.commit()


async def test_regular_price_10_spreads(db):
    await _seed_prices(db)
    price = await calculate_price(db, "20x20", 10, PriceType.regular)
    assert price == Decimal("9400")


async def test_minimum_price_5_spreads(db):
    await _seed_prices(db)
    price = await calculate_price(db, "30x30", 5, PriceType.minimum)
    assert price == Decimal("9700")


async def test_unknown_size_returns_none(db):
    await _seed_prices(db)
    price = await calculate_price(db, "99x99", 10, PriceType.regular)
    assert price is None


async def test_all_regular_prices_match_spec(db):
    await _seed_prices(db)
    expected = {
        ("15x15", 10): Decimal("7570"),
        ("20x20", 10): Decimal("9400"),
        ("25x25", 10): Decimal("13600"),
        ("30x30", 10): Decimal("16700"),
        ("15x15", 5): Decimal("5400"),
        ("20x20", 5): Decimal("7122"),
        ("25x25", 5): Decimal("8700"),
        ("30x30", 5): Decimal("10300"),
    }
    for (size, spreads), expected_price in expected.items():
        price = await calculate_price(db, size, spreads, PriceType.regular)
        assert price == expected_price, f"Failed for {size}/{spreads}: got {price}"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_pricing.py -v
```

Expected: `ImportError` — module not found.

- [ ] **Step 3: Create `app/sales/statuses.py`**

```python
from enum import Enum


class FunnelStatus(str, Enum):
    interested = "interested"
    calculated = "calculated"
    hot = "hot"
    waiting_prepayment = "waiting_prepayment"
    order_created = "order_created"
    needs_curator = "needs_curator"
    lost = "lost"
    no_response = "no_response"
    spam = "spam"
    test = "test"


VALID_TRANSITIONS: dict[FunnelStatus, set[FunnelStatus]] = {
    FunnelStatus.interested: {FunnelStatus.calculated, FunnelStatus.needs_curator, FunnelStatus.lost},
    FunnelStatus.calculated: {FunnelStatus.hot, FunnelStatus.needs_curator, FunnelStatus.lost},
    FunnelStatus.hot: {FunnelStatus.waiting_prepayment, FunnelStatus.needs_curator, FunnelStatus.lost},
    FunnelStatus.waiting_prepayment: {FunnelStatus.order_created, FunnelStatus.needs_curator, FunnelStatus.lost},
    FunnelStatus.order_created: set(),
    FunnelStatus.needs_curator: {FunnelStatus.interested, FunnelStatus.calculated, FunnelStatus.hot, FunnelStatus.lost},
    FunnelStatus.lost: set(),
    FunnelStatus.no_response: {FunnelStatus.interested},
    FunnelStatus.spam: set(),
    FunnelStatus.test: {FunnelStatus.interested},
}
```

- [ ] **Step 4: Create `app/sales/pricing.py`**

```python
from decimal import Decimal
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PriceLadder


class PriceType(str, Enum):
    regular = "regular"
    minimum = "minimum"


async def calculate_price(
    db: AsyncSession,
    size: str,
    spreads_count: int,
    price_type: PriceType = PriceType.regular,
) -> Decimal | None:
    result = await db.execute(
        select(PriceLadder).where(
            PriceLadder.size == size,
            PriceLadder.spreads_count == spreads_count,
            PriceLadder.is_active.is_(True),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return row.regular_price if price_type == PriceType.regular else row.minimum_price


async def get_full_price_table(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(PriceLadder).where(PriceLadder.is_active.is_(True)).order_by(
            PriceLadder.spreads_count.desc(), PriceLadder.size
        )
    )
    rows = result.scalars().all()
    return [
        {
            "size": r.size,
            "spreads_count": r.spreads_count,
            "regular_price": float(r.regular_price),
            "minimum_price": float(r.minimum_price),
            "currency": r.currency,
        }
        for r in rows
    ]
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_pricing.py -v
```

Expected: all 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add app/sales/ tests/test_pricing.py
git commit -m "feat: pricing domain — price ladder lookup and full table query"
```

---

### Task 5: Scripts + FAQ domain

**Files:**
- Create: `app/sales/scripts.py`
- Create: `app/sales/faq.py`
- Create: `tests/test_scripts_faq.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scripts_faq.py
import pytest
from app.db.models import Script, FAQ
from app.sales.scripts import get_relevant_script
from app.sales.faq import get_faq_answer


async def _seed_scripts(db):
    scripts = [
        Script(name="я алиса 1", category="greeting", stage="greeting", body="Привет! Я AI-помощник Монро Бук."),
        Script(name="перед форматом 2", category="sales", stage="format_selection", body="Подскажите, пожалуйста, какой формат рассматриваете?"),
        Script(name="узнаем бюджет", category="objection", stage="objection", objection_type="expensive", body="Подскажите, на какую сумму ориентировались?"),
    ]
    for s in scripts:
        db.add(s)
    await db.commit()


async def _seed_faq(db):
    faqs = [
        FAQ(key="delivery", question="Как доставляете?", answer="Подскажите, пожалуйста, в какой город нужна доставка?"),
        FAQ(key="timing", question="Какие сроки?", answer="Срок зависит от формата. К какой дате нужен подарок?"),
        FAQ(key="similarity", question="Ребёнок будет похож?", answer="Да, мы ориентируемся на фото. Иллюстрации отправим на согласование."),
    ]
    for f in faqs:
        db.add(f)
    await db.commit()


async def test_get_script_by_stage(db):
    await _seed_scripts(db)
    script = await get_relevant_script(db, stage="greeting")
    assert script is not None
    assert "Монро" in script.body


async def test_get_script_by_objection(db):
    await _seed_scripts(db)
    script = await get_relevant_script(db, stage="objection", objection_type="expensive")
    assert script is not None
    assert script.name == "узнаем бюджет"


async def test_get_script_missing_returns_none(db):
    await _seed_scripts(db)
    script = await get_relevant_script(db, stage="nonexistent_stage")
    assert script is None


async def test_get_faq_answer(db):
    await _seed_faq(db)
    answer = await get_faq_answer(db, "delivery")
    assert answer is not None
    assert "город" in answer


async def test_get_faq_missing_returns_none(db):
    await _seed_faq(db)
    answer = await get_faq_answer(db, "unknown_key")
    assert answer is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_scripts_faq.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `app/sales/scripts.py`**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Script


async def get_relevant_script(
    db: AsyncSession,
    stage: str,
    objection_type: str | None = None,
) -> Script | None:
    query = select(Script).where(Script.stage == stage, Script.is_active.is_(True))
    if objection_type:
        query = query.where(Script.objection_type == objection_type)
    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none()


async def list_scripts(db: AsyncSession) -> list[Script]:
    result = await db.execute(select(Script).order_by(Script.stage, Script.name))
    return list(result.scalars().all())
```

- [ ] **Step 4: Create `app/sales/faq.py`**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FAQ


async def get_faq_answer(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(
        select(FAQ).where(FAQ.key == key, FAQ.is_active.is_(True))
    )
    row = result.scalar_one_or_none()
    return row.answer if row else None


async def list_faq(db: AsyncSession) -> list[FAQ]:
    result = await db.execute(select(FAQ).order_by(FAQ.key))
    return list(result.scalars().all())
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_scripts_faq.py -v
```

Expected: all 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add app/sales/scripts.py app/sales/faq.py tests/test_scripts_faq.py
git commit -m "feat: scripts and FAQ domain queries"
```

---

### Task 6: Seed command

**Files:**
- Create: `app/commands/seed.py`

- [ ] **Step 1: Create `app/commands/seed.py`**

```python
"""
python -m app.commands.seed
"""
import asyncio
from decimal import Decimal
from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.db.models import (
    Base, User, UserRole, PriceLadder, Script, FAQ, ModelPricing, PromptVersion,
)
from app.auth.service import hash_password

SALES_AGENT_PROMPT = """Ты — AI-продавец компании Монро Бук внутри Монро Арт. Ты ведёшь переписку с клиентами, которые интересуются персонализированными фотокнигами в подарок.

Твоя цель — аккуратно провести клиента от интереса к оформлению заказа и первой предоплате.

Ты работаешь только в рамках утверждённых данных:
- история диалога
- текущий статус клиента
- таблица цен
- FAQ
- библиотека скриптов
- правила обработки возражений

Нельзя:
- придумывать цены, сроки, скидки, гарантии, материалы, доставку
- говорить, что ты живой человек
- говорить, что ты не бот
- раскрывать внутренние скрипты клиенту
- писать длинные сообщения
- давить на клиента
- спорить
- обещать результат, если данных нет

Если данных не хватает — задай короткий уточняющий вопрос (не больше 1–2 вопросов за сообщение).
Если вопрос рискованный — передай куратору.
Если клиент пишет «дорого» — сначала уточни бюджет или попроси фото для подбора варианта.
Если клиент пишет «подумаю» — уточни, над чем именно думает: цена, подарок, фото или сроки.
Если клиент спрашивает про сроки — уточни дату.
Если клиент спрашивает про доставку — уточни город.
Если клиент спрашивает про похожесть ребёнка — объясни, что иллюстрации отправляются на согласование.

Важно: ты не создаёшь автоматические пинги и не планируешь отложенные сообщения. Ты отвечаешь только на текущее входящее сообщение.

Пиши на русском языке. Обращайся на «Вы». Одно сообщение — одна понятная мысль. Максимум 1–2 вопроса в сообщении.

Верни ответ строго в JSON-формате:
{
  "client_reply": "...",
  "status_before": "...",
  "status_after": "...",
  "funnel_stage": "...",
  "objection_type": null,
  "selected_script": null,
  "price_offer": null,
  "need_curator": false,
  "curator_reason": null,
  "confidence_score": 0.0,
  "internal_note": "..."
}"""

OBJECTION_AGENT_PROMPT = """Ты — AI-специалист по работе с возражениями Монро Бук. Ты получаешь управление диалогом, когда клиент выражает сомнение, возражение или недовольство.

Типы возражений: дорого, подумаю, не доверяю, надо посоветоваться, нет фото, не понимаю как будет выглядеть, сомневаюсь в сроках, боюсь что ребёнок будет не похож, хочу дешевле.

Правила:
- При «дорого» без бюджета — уточни бюджет, не снижай цену сразу.
- При «дорого» с бюджетом — попроси фото, затем подбери вариант.
- При «подумаю» — уточни над чем именно: цена, подарок, фото, сроки.
- При «не доверяю» — предложи реквизиты, отзывы, примеры, связь с куратором. Не утверждай, что ты живой человек.
- Не спорь с клиентом.
- Передай куратору, если клиент продолжает сомневаться после 2 попыток.

Верни ответ в том же JSON-формате, что SalesAgent."""


async def seed():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as db:
        # Users
        for email, role, pwd in [
            ("admin@monroe.ru", UserRole.admin, "admin123"),
            ("curator@monroe.ru", UserRole.curator, "curator123"),
            ("tester@monroe.ru", UserRole.tester, "tester123"),
        ]:
            from sqlalchemy import select
            existing = await db.execute(select(User).where(User.email == email))
            if not existing.scalar_one_or_none():
                db.add(User(email=email, password_hash=hash_password(pwd), role=role))

        # Price ladder (10 spreads)
        prices_10 = [
            ("15x15", 10, "7570", "7000"),
            ("20x20", 10, "9400", "8670"),
            ("25x25", 10, "13600", "12900"),
            ("30x30", 10, "16700", "15800"),
        ]
        # Price ladder (5 spreads)
        prices_5 = [
            ("15x15", 5, "5400", "4600"),
            ("20x20", 5, "7122", "5910"),
            ("25x25", 5, "8700", "8100"),
            ("30x30", 5, "10300", "9700"),
        ]
        from sqlalchemy import select
        for size, spreads, reg, min_p in prices_10 + prices_5:
            ex = await db.execute(
                select(PriceLadder).where(PriceLadder.size == size, PriceLadder.spreads_count == spreads)
            )
            if not ex.scalar_one_or_none():
                db.add(PriceLadder(
                    size=size, spreads_count=spreads,
                    regular_price=Decimal(reg), minimum_price=Decimal(min_p),
                ))

        # Scripts
        script_data = [
            ("я алиса 1", "greeting", "greeting", None, "Добрый день! Я AI-помощник Монро Бук. Чем могу помочь?"),
            ("перед форматом 2", "sales", "format_selection", None, "Подскажите, пожалуйста, какой формат рассматриваете: 15×15, 20×20, 25×25 или 30×30?"),
            ("выберем формат 3", "sales", "format_selection", None, "Давайте подберём формат. Это подарок ребёнку или взрослому?"),
            ("расчет 2020 4", "sales", "calculation", None, "Формат 20×20, 10 разворотов — {price} руб."),
            ("узнаем бюджет", "objection", "objection", "expensive", "Подскажите, пожалуйста, на какую сумму ориентировались? Подберём вариант под Ваш бюджет."),
            ("просим фото 1", "sales", "hot", None, "Пришлите, пожалуйста, фото малыша — подберём лучший вариант."),
            ("поделить на части", "objection", "objection", "expensive", "Оплату можно разделить на части: сначала предоплата, остаток после согласования."),
            ("спишу баллы НОВОЕ", "sales", "calculation", None, "У Вас есть бонусные баллы? Можем учесть при расчёте."),
            ("недоверие", "objection", "objection", "distrust", "Понимаю Ваши сомнения. Мы работаем внутри Монро Арт, можем показать реквизиты, отзывы и примеры. Если хотите — передам диалог куратору."),
            ("отзывы", "trust", "objection", "distrust", "Вот ссылка на наши отзывы. Более 500 довольных клиентов."),
            ("сроки уточнение", "faq", "faq", None, "К какой дате нужен подарок? Уточню сроки по Вашему формату."),
            ("как доставляете", "faq", "faq", None, "В какой город нужна доставка? Подберём оптимальный вариант."),
            ("обратите внимание", "sales", "hot", None, "Обратите внимание: иллюстрации отправляем на согласование, правки вносим до утверждения."),
        ]
        for name, cat, stage, obj, body in script_data:
            ex = await db.execute(select(Script).where(Script.name == name))
            if not ex.scalar_one_or_none():
                db.add(Script(name=name, category=cat, stage=stage, objection_type=obj, body=body))

        # FAQ
        faq_data = [
            ("timing", "Какие сроки?", "Срок зависит от формата и загрузки производства. К какой дате нужен подарок? Сориентирую по возможности."),
            ("fairy_tale", "Как пишете сказку?", "Мы пишем сказки индивидуально. После оформления задам несколько вопросов, редактор подготовит текст и отправит на согласование — можно внести правки."),
            ("delivery", "Как доставляете?", "В какой город нужна доставка? Подберём оптимальный способ."),
            ("similarity", "Ребёнок будет похож?", "Да, мы ориентируемся на фото малыша. Иллюстрации отправим Вам на согласование — можно внести правки до утверждения."),
            ("quality", "Какое качество / из чего книга?", "Книга печатается в подарочном качестве. Детали по материалам уточню по выбранному формату, чтобы не ввести Вас в заблуждение."),
            ("illustrations", "Как делаются иллюстрации?", "После согласования сказки дизайнер рисует иллюстрации по фото малыша и сюжету. Когда готовы — отправим Вам в чат. Правки вносим до согласования."),
            ("payment", "Как оплатить?", "Оплата через безопасную ссылку. Куратор может ответить на вопросы по оплате лично."),
            ("refund", "Возврат?", "По вопросам возврата отвечу через куратора — передам диалог."),
        ]
        for key, question, answer in faq_data:
            ex = await db.execute(select(FAQ).where(FAQ.key == key))
            if not ex.scalar_one_or_none():
                db.add(FAQ(key=key, question=question, answer=answer))

        # Model pricing
        pricing_data = [
            ("openai", "gpt-4o", "2.50", "10.00", "USD"),
            ("openai", "gpt-4o-mini", "0.15", "0.60", "USD"),
            ("anthropic", "claude-sonnet-4-6", "3.00", "15.00", "USD"),
            ("anthropic", "claude-haiku-4-5-20251001", "0.80", "4.00", "USD"),
        ]
        for provider, model, inp, out, cur in pricing_data:
            ex = await db.execute(
                select(ModelPricing).where(ModelPricing.provider == provider, ModelPricing.model == model)
            )
            if not ex.scalar_one_or_none():
                db.add(ModelPricing(
                    provider=provider, model=model,
                    input_price_per_1m=Decimal(inp), output_price_per_1m=Decimal(out),
                    currency=cur,
                ))

        # Prompt versions
        for name, version, content in [
            ("sales_agent_v1", "1.0", SALES_AGENT_PROMPT),
            ("objection_agent_v1", "1.0", OBJECTION_AGENT_PROMPT),
        ]:
            ex = await db.execute(
                select(PromptVersion).where(PromptVersion.name == name, PromptVersion.version == version)
            )
            if not ex.scalar_one_or_none():
                db.add(PromptVersion(name=name, version=version, content=content, is_active=True))

        await db.commit()
        print("Seed complete.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
```

- [ ] **Step 2: Run seed**

```bash
python -m app.commands.seed
```

Expected: `Seed complete.`

- [ ] **Step 3: Verify data**

```bash
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, func
from app.config import settings
from app.db.models import User, Script, FAQ, PriceLadder

async def check():
    engine = create_async_engine(settings.DATABASE_URL)
    S = async_sessionmaker(engine)
    async with S() as db:
        for model in [User, Script, FAQ, PriceLadder]:
            r = await db.execute(select(func.count()).select_from(model))
            print(model.__tablename__, r.scalar())
    await engine.dispose()

asyncio.run(check())
"
```

Expected output:
```
users 3
scripts 13
faq 8
price_ladder 8
```

- [ ] **Step 4: Commit**

```bash
git add app/commands/seed.py
git commit -m "feat: seed command — users, prices, scripts, FAQ, model pricing, prompts"
```

---

### Task 7: CRM adapter

**Files:**
- Create: `app/crm/base.py`
- Create: `app/crm/mock.py`
- Create: `tests/test_crm.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_crm.py
import pytest
from app.crm.mock import MockCRMAdapter


async def test_fetch_client_returns_dict():
    adapter = MockCRMAdapter()
    client = await adapter.fetch_client("crm-client-1")
    assert client["crm_client_id"] == "crm-client-1"
    assert "name" in client


async def test_fetch_dialog_returns_dict():
    adapter = MockCRMAdapter()
    dialog = await adapter.fetch_dialog("crm-dialog-1")
    assert dialog["crm_dialog_id"] == "crm-dialog-1"
    assert "messages" in dialog


async def test_send_reply_returns_message_id():
    adapter = MockCRMAdapter()
    result = await adapter.send_reply("crm-dialog-1", "Привет!")
    assert "message_id" in result


async def test_update_status_succeeds():
    adapter = MockCRMAdapter()
    result = await adapter.update_status("crm-client-1", "hot")
    assert result is True
```

- [ ] **Step 2: Create `app/crm/base.py`**

```python
from abc import ABC, abstractmethod


class CRMAdapter(ABC):
    @abstractmethod
    async def fetch_client(self, client_id: str) -> dict:
        ...

    @abstractmethod
    async def fetch_dialog(self, dialog_id: str) -> dict:
        ...

    @abstractmethod
    async def send_reply(self, dialog_id: str, text: str) -> dict:
        ...

    @abstractmethod
    async def update_status(self, client_id: str, status: str) -> bool:
        ...
```

- [ ] **Step 3: Create `app/crm/mock.py`**

```python
import uuid
from app.crm.base import CRMAdapter


class MockCRMAdapter(CRMAdapter):
    async def fetch_client(self, client_id: str) -> dict:
        return {
            "crm_client_id": client_id,
            "name": f"Тест Клиент {client_id}",
            "source": "vk",
        }

    async def fetch_dialog(self, dialog_id: str) -> dict:
        return {
            "crm_dialog_id": dialog_id,
            "messages": [],
            "client_id": f"client-{dialog_id}",
        }

    async def send_reply(self, dialog_id: str, text: str) -> dict:
        return {
            "message_id": str(uuid.uuid4()),
            "dialog_id": dialog_id,
            "status": "draft",
            "text": text,
        }

    async def update_status(self, client_id: str, status: str) -> bool:
        return True


def get_crm_adapter() -> CRMAdapter:
    return MockCRMAdapter()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_crm.py -v
```

Expected: all 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/crm/ tests/test_crm.py
git commit -m "feat: CRM adapter interface and MockCRMAdapter"
```

---

### Task 8: AI schemas + cost calculation

**Files:**
- Create: `app/ai/schemas.py`
- Create: `app/ai/cost.py`
- Create: `tests/test_cost.py`

- [ ] **Step 1: Write failing cost tests**

```python
# tests/test_cost.py
import pytest
from decimal import Decimal
from app.ai.cost import calculate_cost, estimate_tokens
from app.db.models import ModelPricing


def make_pricing(inp: str, out: str) -> ModelPricing:
    p = ModelPricing()
    p.input_price_per_1m = Decimal(inp)
    p.output_price_per_1m = Decimal(out)
    p.currency = "USD"
    return p


def test_calculate_cost_gpt4o():
    pricing = make_pricing("2.50", "10.00")
    cost = calculate_cost(input_tokens=1000, output_tokens=500, pricing=pricing)
    # 1000/1M * 2.50 + 500/1M * 10.00 = 0.0025 + 0.005 = 0.0075
    assert cost == Decimal("0.007500")


def test_calculate_cost_zero_tokens():
    pricing = make_pricing("2.50", "10.00")
    cost = calculate_cost(input_tokens=0, output_tokens=0, pricing=pricing)
    assert cost == Decimal("0.000000")


def test_calculate_cost_large_run():
    pricing = make_pricing("3.00", "15.00")
    cost = calculate_cost(input_tokens=10000, output_tokens=2000, pricing=pricing)
    # 10000/1M*3 + 2000/1M*15 = 0.03 + 0.03 = 0.06
    assert cost == Decimal("0.060000")


def test_estimate_tokens_short_text():
    tokens = estimate_tokens("Привет! Как дела?")
    assert 3 <= tokens <= 10


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0
```

- [ ] **Step 2: Create `app/ai/schemas.py`**

```python
from pydantic import BaseModel, Field


class AgentOutput(BaseModel):
    client_reply: str
    status_before: str
    status_after: str
    funnel_stage: str
    objection_type: str | None = None
    selected_script: str | None = None
    price_offer: float | None = None
    need_curator: bool = False
    curator_reason: str | None = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    internal_note: str
```

- [ ] **Step 3: Create `app/ai/cost.py`**

```python
from decimal import Decimal

from app.db.models import ModelPricing


def calculate_cost(input_tokens: int, output_tokens: int, pricing: ModelPricing) -> Decimal:
    input_cost = Decimal(input_tokens) / Decimal(1_000_000) * pricing.input_price_per_1m
    output_cost = Decimal(output_tokens) / Decimal(1_000_000) * pricing.output_price_per_1m
    return (input_cost + output_cost).quantize(Decimal("0.000001"))


def estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 chars for mixed Russian/English."""
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cost.py -v
```

Expected: all 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/ai/schemas.py app/ai/cost.py tests/test_cost.py
git commit -m "feat: AI schemas (AgentOutput) and cost calculation"
```

---

### Task 9: AI tools

**Files:**
- Create: `app/ai/tools.py`

- [ ] **Step 1: Create `app/ai/tools.py`**

```python
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from agents import function_tool, RunContextWrapper
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Client, CuratorReview, Dialog, DialogStatus, FAQ, Message, MessageRole,
    PriceLadder, ReviewStatus, Script, StatusHistory,
)
from app.sales.pricing import PriceType, calculate_price, get_full_price_table


@dataclass
class AgentRunContext:
    db: AsyncSession
    dialog_id: int
    client_id: int


@function_tool
async def get_client_context(ctx: RunContextWrapper[AgentRunContext]) -> str:
    """Returns client info, dialog status, and message history."""
    db = ctx.context.db
    dialog_id = ctx.context.dialog_id
    client_id = ctx.context.client_id

    dialog = await db.get(Dialog, dialog_id)
    client = await db.get(Client, client_id)

    messages_result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id)
        .order_by(Message.created_at)
        .limit(50)
    )
    messages = messages_result.scalars().all()

    return json.dumps({
        "client": {
            "id": client.id,
            "name": client.name,
            "source": client.source,
        },
        "dialog": {
            "id": dialog.id,
            "current_status": dialog.current_status.value,
            "is_test": dialog.is_test,
            "last_message_at": dialog.last_message_at.isoformat() if dialog.last_message_at else None,
        },
        "messages": [
            {
                "role": m.role.value,
                "text": m.text,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }, ensure_ascii=False)


@function_tool
async def get_price_ladder(ctx: RunContextWrapper[AgentRunContext]) -> str:
    """Returns full photobook price table."""
    db = ctx.context.db
    table = await get_full_price_table(db)
    return json.dumps(table, ensure_ascii=False)


@function_tool
async def calculate_photobook_price(
    ctx: RunContextWrapper[AgentRunContext],
    size: str,
    spreads_count: int,
    price_type: str = "regular",
) -> str:
    """Calculate price for a photobook. size: '15x15'|'20x20'|'25x25'|'30x30'. spreads_count: 5|10. price_type: 'regular'|'minimum'."""
    db = ctx.context.db
    pt = PriceType.minimum if price_type == "minimum" else PriceType.regular
    price = await calculate_price(db, size, spreads_count, pt)
    if price is None:
        return f"Цена не найдена для размера {size}, {spreads_count} разворотов."
    return f"{price} руб."


@function_tool
async def get_relevant_script(
    ctx: RunContextWrapper[AgentRunContext],
    stage: str,
    objection_type: str = "",
) -> str:
    """Returns script body for current sales stage. objection_type optional."""
    db = ctx.context.db
    query = select(Script).where(Script.stage == stage, Script.is_active.is_(True))
    if objection_type:
        query = query.where(Script.objection_type == objection_type)
    result = await db.execute(query.limit(1))
    script = result.scalar_one_or_none()
    if script is None:
        return "Скрипт не найден."
    return json.dumps({
        "name": script.name,
        "body": script.body,
        "stage": script.stage,
    }, ensure_ascii=False)


@function_tool
async def get_faq_answer(ctx: RunContextWrapper[AgentRunContext], question_type: str) -> str:
    """Returns approved FAQ answer. question_type: 'timing'|'delivery'|'similarity'|'quality'|'illustrations'|'fairy_tale'|'payment'|'refund'."""
    db = ctx.context.db
    result = await db.execute(
        select(FAQ).where(FAQ.key == question_type, FAQ.is_active.is_(True))
    )
    faq = result.scalar_one_or_none()
    if faq is None:
        return "Ответ не найден. Уточни вопрос у куратора."
    return faq.answer


@function_tool
async def update_client_status(
    ctx: RunContextWrapper[AgentRunContext],
    new_status: str,
    reason: str,
) -> str:
    """Update dialog status and record history."""
    db = ctx.context.db
    dialog = await db.get(Dialog, ctx.context.dialog_id)
    old_status = dialog.current_status.value
    try:
        dialog.current_status = DialogStatus[new_status]
    except KeyError:
        return f"Unknown status: {new_status}"
    dialog.updated_at = datetime.utcnow()
    db.add(StatusHistory(
        dialog_id=ctx.context.dialog_id,
        old_status=old_status,
        new_status=new_status,
        reason=reason,
    ))
    await db.commit()
    return f"Status updated: {old_status} → {new_status}"


@function_tool
async def request_curator_review(
    ctx: RunContextWrapper[AgentRunContext],
    reason: str,
    ai_draft: str,
) -> str:
    """Create pending curator review task."""
    db = ctx.context.db
    review = CuratorReview(
        dialog_id=ctx.context.dialog_id,
        status=ReviewStatus.pending,
        ai_draft=ai_draft,
        reason=reason,
    )
    db.add(review)
    dialog = await db.get(Dialog, ctx.context.dialog_id)
    dialog.current_status = DialogStatus.needs_curator
    await db.commit()
    await db.refresh(review)
    return f"Curator review created: id={review.id}"


@function_tool
async def fetch_crm_dialog(ctx: RunContextWrapper[AgentRunContext]) -> str:
    """Stub: fetch raw dialog data from CRM."""
    return json.dumps({
        "dialog_id": ctx.context.dialog_id,
        "note": "CRM integration not yet connected. Using local DB data.",
    })


@function_tool
async def send_crm_reply(
    ctx: RunContextWrapper[AgentRunContext],
    text: str,
) -> str:
    """Stub: send reply via CRM (saves as draft in MVP draft_only mode)."""
    from app.config import settings
    if settings.AI_SEND_MODE == "draft_only":
        return f"DRAFT (not sent): {text[:80]}..."
    return f"Sent to CRM dialog {ctx.context.dialog_id}: {text[:80]}..."


ALL_SALES_TOOLS = [
    get_client_context,
    get_price_ladder,
    calculate_photobook_price,
    get_relevant_script,
    get_faq_answer,
    update_client_status,
    request_curator_review,
    fetch_crm_dialog,
    send_crm_reply,
]

OBJECTION_TOOLS = [
    get_client_context,
    get_relevant_script,
    get_faq_answer,
    calculate_photobook_price,
    request_curator_review,
]
```

- [ ] **Step 2: Verify imports**

```bash
python -c "from app.ai.tools import ALL_SALES_TOOLS; print(len(ALL_SALES_TOOLS), 'tools loaded')"
```

Expected: `9 tools loaded`

- [ ] **Step 3: Commit**

```bash
git add app/ai/tools.py
git commit -m "feat: AI tools — pricing, scripts, FAQ, status, curator handoff, CRM stubs"
```

---

### Task 10: AI agents + prompts + providers

**Files:**
- Create: `app/ai/prompts.py`
- Create: `app/ai/providers.py`
- Create: `app/ai/agents.py`

- [ ] **Step 1: Create `app/ai/prompts.py`**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromptVersion


async def load_prompt(db: AsyncSession, name: str) -> str:
    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.name == name,
            PromptVersion.is_active.is_(True),
        ).order_by(PromptVersion.id.desc()).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError(f"Prompt '{name}' not found in DB. Run seed first.")
    return row.content
```

- [ ] **Step 2: Create `app/ai/providers.py`**

```python
import os
from agents.extensions.models.litellm_model import LiteLLMModel
from app.config import settings


def get_model(provider: str | None = None, model_name: str | None = None) -> LiteLLMModel:
    provider = provider or settings.AI_PROVIDER
    model_name = model_name or settings.MODEL_NAME

    if provider == "openai":
        os.environ.setdefault("OPENAI_API_KEY", settings.OPENAI_API_KEY)
        return LiteLLMModel(model=model_name)

    if provider == "anthropic":
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY)
        return LiteLLMModel(model=f"anthropic/{model_name}")

    raise ValueError(f"Unknown provider: {provider}. Use 'openai' or 'anthropic'.")
```

- [ ] **Step 3: Create `app/ai/agents.py`**

```python
from agents import Agent
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import load_prompt
from app.ai.providers import get_model
from app.ai.schemas import AgentOutput
from app.ai.tools import ALL_SALES_TOOLS, OBJECTION_TOOLS


async def build_objection_agent(db: AsyncSession) -> Agent:
    prompt = await load_prompt(db, "objection_agent_v1")
    return Agent(
        name="ObjectionAgent",
        instructions=prompt,
        model=get_model(),
        tools=OBJECTION_TOOLS,
        output_type=AgentOutput,
    )


async def build_sales_agent(db: AsyncSession) -> Agent:
    prompt = await load_prompt(db, "sales_agent_v1")
    objection_agent = await build_objection_agent(db)

    return Agent(
        name="SalesAgent",
        instructions=prompt,
        model=get_model(),
        tools=ALL_SALES_TOOLS,
        handoffs=[objection_agent],
        output_type=AgentOutput,
    )
```

- [ ] **Step 4: Commit**

```bash
git add app/ai/prompts.py app/ai/providers.py app/ai/agents.py
git commit -m "feat: AI agents — SalesAgent, ObjectionAgent, LiteLLM provider"
```

---

### Task 11: AI runner

**Files:**
- Create: `app/ai/runner.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: Write failing runner tests**

```python
# tests/test_runner.py
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.schemas import AgentOutput
from app.ai.runner import run_agent_for_dialog
from app.db.models import (
    Client, Dialog, DialogStatus, Message, MessageRole,
    ModelPricing, PromptVersion, CuratorReview, ReviewStatus,
)


def make_agent_output(**kwargs) -> AgentOutput:
    defaults = dict(
        client_reply="Добрый день! Чем могу помочь?",
        status_before="interested",
        status_after="interested",
        funnel_stage="greeting",
        objection_type=None,
        selected_script="я алиса 1",
        price_offer=None,
        need_curator=False,
        curator_reason=None,
        confidence_score=0.87,
        internal_note="Test run",
    )
    defaults.update(kwargs)
    return AgentOutput(**defaults)


async def _setup_dialog(db):
    client = Client(name="Тест", source="test")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, is_test=True, current_status=DialogStatus.interested)
    db.add(dialog)
    pricing = ModelPricing(
        provider="openai", model="gpt-4o",
        input_price_per_1m=Decimal("2.50"), output_price_per_1m=Decimal("10.00"),
    )
    db.add(pricing)
    db.add(PromptVersion(name="sales_agent_v1", version="1.0", content="Test prompt", is_active=True))
    db.add(PromptVersion(name="objection_agent_v1", version="1.0", content="Test prompt", is_active=True))
    await db.commit()
    await db.refresh(dialog)
    return dialog, client


async def test_runner_persists_ai_run(db):
    dialog, client = await _setup_dialog(db)
    mock_result = MagicMock()
    mock_result.final_output = make_agent_output()
    mock_result.usage = MagicMock(input_tokens=200, output_tokens=80)

    with patch("app.ai.runner.Runner.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        ai_run = await run_agent_for_dialog(db, dialog.id, client.id, "Привет")

    assert ai_run.input_tokens == 200
    assert ai_run.output_tokens == 80
    assert ai_run.cost_amount is not None
    assert ai_run.need_curator is False


async def test_runner_creates_curator_review_on_low_confidence(db):
    dialog, client = await _setup_dialog(db)
    mock_result = MagicMock()
    mock_result.final_output = make_agent_output(confidence_score=0.50, need_curator=False)
    mock_result.usage = MagicMock(input_tokens=100, output_tokens=50)

    with patch("app.ai.runner.Runner.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        ai_run = await run_agent_for_dialog(db, dialog.id, client.id, "Тест")

    from sqlalchemy import select
    result = await db.execute(select(CuratorReview).where(CuratorReview.dialog_id == dialog.id))
    review = result.scalar_one_or_none()
    assert review is not None
    assert review.status == ReviewStatus.pending


async def test_runner_creates_curator_review_when_flagged(db):
    dialog, client = await _setup_dialog(db)
    mock_result = MagicMock()
    mock_result.final_output = make_agent_output(
        confidence_score=0.90,
        need_curator=True,
        curator_reason="Клиент просит договор",
    )
    mock_result.usage = MagicMock(input_tokens=100, output_tokens=50)

    with patch("app.ai.runner.Runner.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        ai_run = await run_agent_for_dialog(db, dialog.id, client.id, "Тест")

    assert ai_run.need_curator is True
    from sqlalchemy import select
    result = await db.execute(select(CuratorReview).where(CuratorReview.dialog_id == dialog.id))
    review = result.scalar_one_or_none()
    assert review is not None


async def test_runner_no_followup_tasks_created(db):
    """AI must not create scheduled or followup tasks — replies only on incoming message."""
    dialog, client = await _setup_dialog(db)
    mock_result = MagicMock()
    mock_result.final_output = make_agent_output(confidence_score=0.90)
    mock_result.usage = MagicMock(input_tokens=100, output_tokens=50)

    with patch("app.ai.runner.Runner.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        ai_run = await run_agent_for_dialog(db, dialog.id, client.id, "Тест")

    # No scheduled tasks exist — runner has no scheduling mechanism
    assert ai_run.raw_response is not None
    raw = ai_run.raw_response
    assert "scheduled" not in str(raw).lower()
    assert "followup" not in str(raw).lower()
    assert "ping" not in str(raw).lower()
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_runner.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `app/ai/runner.py`**

```python
import time
from datetime import datetime

from agents import Runner
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import build_sales_agent
from app.ai.cost import calculate_cost, estimate_tokens
from app.ai.schemas import AgentOutput
from app.ai.tools import AgentRunContext
from app.config import settings
from app.db.models import (
    AIRun, CuratorReview, Dialog, Message, MessageRole, ModelPricing, ReviewStatus,
)


async def _get_active_pricing(db: AsyncSession, provider: str, model: str) -> ModelPricing | None:
    result = await db.execute(
        select(ModelPricing).where(
            ModelPricing.provider == provider,
            ModelPricing.model == model,
            ModelPricing.is_active.is_(True),
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def _build_message_history(db: AsyncSession, dialog_id: int) -> list[dict]:
    result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id)
        .order_by(Message.created_at)
        .limit(50)
    )
    messages = result.scalars().all()
    history = []
    for m in messages:
        if m.role == MessageRole.client:
            history.append({"role": "user", "content": m.text})
        elif m.role == MessageRole.ai:
            history.append({"role": "assistant", "content": m.text})
    return history


async def run_agent_for_dialog(
    db: AsyncSession,
    dialog_id: int,
    client_id: int,
    incoming_text: str,
) -> AIRun:
    dialog = await db.get(Dialog, dialog_id)
    status_before = dialog.current_status.value

    # Save incoming message
    incoming_msg = Message(
        dialog_id=dialog_id,
        role=MessageRole.client,
        text=incoming_text,
    )
    db.add(incoming_msg)
    dialog.last_message_at = datetime.utcnow()
    await db.commit()
    await db.refresh(incoming_msg)

    # Build context + history
    context = AgentRunContext(db=db, dialog_id=dialog_id, client_id=client_id)
    history = await _build_message_history(db, dialog_id)

    # Run agent
    agent = await build_sales_agent(db)
    start_ms = time.time()
    result = await Runner.run(agent, history, context=context)
    latency_ms = int((time.time() - start_ms) * 1000)

    output: AgentOutput = result.final_output

    # Save AI reply message
    ai_msg = Message(
        dialog_id=dialog_id,
        role=MessageRole.ai,
        text=output.client_reply,
    )
    db.add(ai_msg)
    await db.flush()

    # Calculate cost
    cost_estimated = False
    if hasattr(result, "usage") and result.usage:
        input_tokens = result.usage.input_tokens
        output_tokens = result.usage.output_tokens
    else:
        input_tokens = estimate_tokens(" ".join(m["content"] for m in history))
        output_tokens = estimate_tokens(output.client_reply)
        cost_estimated = True

    total_tokens = input_tokens + output_tokens
    pricing = await _get_active_pricing(db, settings.AI_PROVIDER, settings.MODEL_NAME)
    cost_amount = calculate_cost(input_tokens, output_tokens, pricing) if pricing else None
    cost_currency = pricing.currency if pricing else "USD"

    # Persist ai_run
    ai_run = AIRun(
        dialog_id=dialog_id,
        input_message_id=incoming_msg.id,
        output_message_id=ai_msg.id,
        provider=settings.AI_PROVIDER,
        model=settings.MODEL_NAME,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_amount=cost_amount,
        cost_currency=cost_currency,
        cost_estimated=cost_estimated,
        latency_ms=latency_ms,
        confidence_score=output.confidence_score,
        need_curator=output.need_curator,
        curator_reason=output.curator_reason,
        selected_script=output.selected_script,
        status_before=status_before,
        status_after=output.status_after,
        raw_response=output.model_dump(),
    )
    db.add(ai_run)
    await db.flush()

    # Create curator review if needed
    needs_review = output.need_curator or output.confidence_score < settings.CONFIDENCE_THRESHOLD
    if needs_review:
        review = CuratorReview(
            dialog_id=dialog_id,
            ai_run_id=ai_run.id,
            status=ReviewStatus.pending,
            ai_draft=output.client_reply,
            reason=output.curator_reason or f"Low confidence: {output.confidence_score:.2f}",
        )
        db.add(review)

    # Update dialog status
    from app.db.models import DialogStatus
    try:
        dialog.current_status = DialogStatus[output.status_after]
    except KeyError:
        pass
    dialog.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(ai_run)
    return ai_run
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_runner.py -v
```

Expected: all 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/ai/runner.py tests/test_runner.py
git commit -m "feat: AI runner — agent execution, cost logging, curator review creation"
```

---

### Task 12: CRM webhook + dialogs API

**Files:**
- Create: `app/api/crm_webhook.py`
- Create: `app/api/dialogs.py`
- Modify: `app/main.py`
- Create: `tests/test_crm_webhook.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_crm_webhook.py
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.schemas import AgentOutput
from app.db.models import ModelPricing, PromptVersion


def make_agent_output(**kw):
    return AgentOutput(
        client_reply="Здравствуйте!",
        status_before="interested", status_after="interested",
        funnel_stage="greeting", confidence_score=0.88,
        need_curator=False, internal_note="ok",
    )


async def _seed_pricing(db):
    db.add(ModelPricing(
        provider="openai", model="gpt-4o",
        input_price_per_1m=Decimal("2.50"), output_price_per_1m=Decimal("10.00"),
    ))
    db.add(PromptVersion(name="sales_agent_v1", version="1.0", content="p", is_active=True))
    db.add(PromptVersion(name="objection_agent_v1", version="1.0", content="p", is_active=True))
    await db.commit()


async def test_webhook_creates_dialog_and_client(client, db):
    await _seed_pricing(db)
    mock_result = MagicMock(final_output=make_agent_output(), usage=MagicMock(input_tokens=10, output_tokens=5))
    with patch("app.api.crm_webhook.run_agent_for_dialog", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = MagicMock(
            id=1, need_curator=False, confidence_score=0.88,
            cost_amount=Decimal("0.001"), cost_currency="USD",
            status_after="interested",
        )
        resp = await client.post("/crm/webhook/message", json={
            "crm_dialog_id": "vk-dialog-001",
            "crm_client_id": "vk-client-001",
            "client_name": "Тест Клиент",
            "text": "Привет, хочу фотокнигу",
            "external_message_id": "msg-001",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert "ai_run_id" in data
    assert "dialog_id" in data


async def test_webhook_same_dialog_id_reuses_dialog(client, db):
    await _seed_pricing(db)
    payload = {
        "crm_dialog_id": "vk-dialog-002",
        "crm_client_id": "vk-client-002",
        "client_name": "Клиент 2",
        "text": "Первое сообщение",
    }
    mock_ai_run = MagicMock(
        id=1, need_curator=False, confidence_score=0.88,
        cost_amount=Decimal("0.001"), cost_currency="USD",
        status_after="interested",
    )
    with patch("app.api.crm_webhook.run_agent_for_dialog", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_ai_run
        await client.post("/crm/webhook/message", json=payload)
        payload["text"] = "Второе сообщение"
        resp = await client.post("/crm/webhook/message", json=payload)

    assert resp.status_code == 200
    # Same dialog_id returned both times
    assert mock_run.call_count == 2
    first_dialog_id = mock_run.call_args_list[0][0][1]
    second_dialog_id = mock_run.call_args_list[1][0][1]
    assert first_dialog_id == second_dialog_id
```

- [ ] **Step 2: Create `app/api/crm_webhook.py`**

```python
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.runner import run_agent_for_dialog
from app.db.models import Client, Dialog, DialogStatus
from app.db.session import get_db

router = APIRouter()


class WebhookMessageRequest(BaseModel):
    crm_dialog_id: str
    crm_client_id: str
    client_name: str | None = None
    text: str
    external_message_id: str | None = None
    source: str = "crm"


class WebhookMessageResponse(BaseModel):
    ai_run_id: int
    dialog_id: int
    need_curator: bool
    confidence_score: float
    cost_amount: float | None
    cost_currency: str
    status_after: str


@router.post("/webhook/message", response_model=WebhookMessageResponse)
async def receive_crm_message(body: WebhookMessageRequest, db: AsyncSession = Depends(get_db)):
    # Upsert client
    result = await db.execute(select(Client).where(Client.crm_client_id == body.crm_client_id))
    client = result.scalar_one_or_none()
    if client is None:
        client = Client(
            crm_client_id=body.crm_client_id,
            name=body.client_name,
            source=body.source,
        )
        db.add(client)
        await db.flush()

    # Upsert dialog
    result = await db.execute(select(Dialog).where(Dialog.crm_dialog_id == body.crm_dialog_id))
    dialog = result.scalar_one_or_none()
    if dialog is None:
        dialog = Dialog(
            crm_dialog_id=body.crm_dialog_id,
            client_id=client.id,
            current_status=DialogStatus.interested,
        )
        db.add(dialog)
        await db.flush()

    await db.commit()
    await db.refresh(dialog)
    await db.refresh(client)

    ai_run = await run_agent_for_dialog(db, dialog.id, client.id, body.text)

    return WebhookMessageResponse(
        ai_run_id=ai_run.id,
        dialog_id=dialog.id,
        need_curator=ai_run.need_curator,
        confidence_score=float(ai_run.confidence_score or 0),
        cost_amount=float(ai_run.cost_amount) if ai_run.cost_amount else None,
        cost_currency=ai_run.cost_currency,
        status_after=ai_run.status_after or "interested",
    )
```

- [ ] **Step 3: Create `app/api/dialogs.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import Dialog, Message, User
from app.db.session import get_db

router = APIRouter()


class DialogSummary(BaseModel):
    id: int
    crm_dialog_id: str | None
    current_status: str
    is_test: bool
    last_message_at: str | None
    client_id: int

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    role: str
    text: str
    created_at: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[DialogSummary])
async def list_dialogs(
    status: str | None = None,
    is_test: bool | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Dialog).order_by(desc(Dialog.last_message_at))
    if status:
        from app.db.models import DialogStatus
        query = query.where(Dialog.current_status == DialogStatus[status])
    if is_test is not None:
        query = query.where(Dialog.is_test == is_test)
    result = await db.execute(query)
    dialogs = result.scalars().all()
    return [
        DialogSummary(
            id=d.id,
            crm_dialog_id=d.crm_dialog_id,
            current_status=d.current_status.value,
            is_test=d.is_test,
            last_message_at=d.last_message_at.isoformat() if d.last_message_at else None,
            client_id=d.client_id,
        )
        for d in dialogs
    ]


@router.get("/{dialog_id}/messages", response_model=list[MessageOut])
async def get_messages(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Message).where(Message.dialog_id == dialog_id).order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return [
        MessageOut(
            id=m.id,
            role=m.role.value,
            text=m.text,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]
```

- [ ] **Step 4: Register routers in `app/main.py`**

Add after auth router:

```python
from app.api.crm_webhook import router as crm_router
from app.api.dialogs import router as dialogs_router

app.include_router(crm_router, prefix="/crm", tags=["crm"])
app.include_router(dialogs_router, prefix="/dialogs", tags=["dialogs"])
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_crm_webhook.py -v
```

Expected: all 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add app/api/crm_webhook.py app/api/dialogs.py app/main.py tests/test_crm_webhook.py
git commit -m "feat: CRM webhook and dialogs API"
```

---

### Task 13: AI test-chat API

**Files:**
- Create: `app/api/ai.py`
- Create: `tests/test_chat.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_chat.py
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.models import Client, Dialog, DialogStatus, ModelPricing, PromptVersion, UserRole
from app.auth.service import hash_password, create_access_token


async def _setup(db):
    from app.db.models import User
    user = User(email="t@t.ru", password_hash=hash_password("pw"), role=UserRole.tester)
    db.add(user)
    client = Client(name="Tester Client", source="test")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, is_test=True, current_status=DialogStatus.test)
    db.add(dialog)
    db.add(ModelPricing(
        provider="openai", model="gpt-4o",
        input_price_per_1m=Decimal("2.50"), output_price_per_1m=Decimal("10.00"),
    ))
    db.add(PromptVersion(name="sales_agent_v1", version="1.0", content="p", is_active=True))
    db.add(PromptVersion(name="objection_agent_v1", version="1.0", content="p", is_active=True))
    await db.commit()
    await db.refresh(user)
    await db.refresh(dialog)
    return user, dialog


async def test_test_chat_returns_agent_output(client, db):
    user, dialog = await _setup(db)
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    mock_ai_run = MagicMock(
        id=1, need_curator=False, confidence_score=0.88,
        cost_amount=Decimal("0.002"), cost_currency="USD",
        status_after="interested",
        raw_response={
            "client_reply": "Здравствуйте!",
            "status_before": "test",
            "status_after": "interested",
            "funnel_stage": "greeting",
            "objection_type": None,
            "selected_script": "я алиса 1",
            "price_offer": None,
            "need_curator": False,
            "curator_reason": None,
            "confidence_score": 0.88,
            "internal_note": "ok",
        },
    )

    with patch("app.api.ai.run_agent_for_dialog", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_ai_run
        resp = await client.post(
            "/ai/test-chat",
            json={"dialog_id": dialog.id, "text": "Привет"},
            headers=headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["client_reply"] == "Здравствуйте!"
    assert data["confidence_score"] == 0.88
    assert data["cost_amount"] == pytest.approx(0.002)


async def test_test_chat_requires_auth(client, db):
    resp = await client.post("/ai/test-chat", json={"dialog_id": 1, "text": "hi"})
    assert resp.status_code == 401
```

- [ ] **Step 2: Create `app/api/ai.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.runner import run_agent_for_dialog
from app.auth.dependencies import get_current_user
from app.db.models import AIRun, Client, Dialog, DialogStatus, User
from app.db.session import get_db

router = APIRouter()


class TestChatRequest(BaseModel):
    dialog_id: int | None = None
    text: str


class TestChatResponse(BaseModel):
    ai_run_id: int
    dialog_id: int
    client_reply: str
    status_before: str
    status_after: str
    funnel_stage: str
    objection_type: str | None
    selected_script: str | None
    price_offer: float | None
    need_curator: bool
    curator_reason: str | None
    confidence_score: float
    internal_note: str
    cost_amount: float | None
    cost_currency: str


class AIRunDetail(BaseModel):
    id: int
    dialog_id: int
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cost_amount: float | None
    cost_currency: str
    cost_estimated: bool
    confidence_score: float | None
    need_curator: bool
    selected_script: str | None
    status_before: str | None
    status_after: str | None
    latency_ms: int | None


@router.post("/test-chat", response_model=TestChatResponse)
async def test_chat(
    body: TestChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dialog_id = body.dialog_id

    # Create new test dialog if none provided
    if dialog_id is None:
        from app.db.models import Client
        client = Client(name=f"Tester: {current_user.email}", source="test")
        db.add(client)
        await db.flush()
        dialog = Dialog(
            client_id=client.id,
            current_status=DialogStatus.interested,
            is_test=True,
        )
        db.add(dialog)
        await db.commit()
        await db.refresh(dialog)
        await db.refresh(client)
        dialog_id = dialog.id
        client_id = client.id
    else:
        result = await db.execute(select(Dialog).where(Dialog.id == dialog_id))
        dialog = result.scalar_one_or_none()
        if dialog is None:
            raise HTTPException(status_code=404, detail="Dialog not found")
        client_id = dialog.client_id

    ai_run = await run_agent_for_dialog(db, dialog_id, client_id, body.text)
    raw = ai_run.raw_response or {}

    return TestChatResponse(
        ai_run_id=ai_run.id,
        dialog_id=dialog_id,
        client_reply=raw.get("client_reply", ""),
        status_before=raw.get("status_before", ""),
        status_after=ai_run.status_after or "",
        funnel_stage=raw.get("funnel_stage", ""),
        objection_type=raw.get("objection_type"),
        selected_script=ai_run.selected_script,
        price_offer=raw.get("price_offer"),
        need_curator=ai_run.need_curator,
        curator_reason=ai_run.curator_reason,
        confidence_score=float(ai_run.confidence_score or 0),
        internal_note=raw.get("internal_note", ""),
        cost_amount=float(ai_run.cost_amount) if ai_run.cost_amount else None,
        cost_currency=ai_run.cost_currency,
    )


@router.get("/runs/{run_id}", response_model=AIRunDetail)
async def get_ai_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    run = await db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AI run not found")
    return AIRunDetail(
        id=run.id,
        dialog_id=run.dialog_id,
        provider=run.provider,
        model=run.model,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cost_amount=float(run.cost_amount) if run.cost_amount else None,
        cost_currency=run.cost_currency,
        cost_estimated=run.cost_estimated,
        confidence_score=float(run.confidence_score) if run.confidence_score else None,
        need_curator=run.need_curator,
        selected_script=run.selected_script,
        status_before=run.status_before,
        status_after=run.status_after,
        latency_ms=run.latency_ms,
    )
```

- [ ] **Step 3: Register in `app/main.py`**

```python
from app.api.ai import router as ai_router
app.include_router(ai_router, prefix="/ai", tags=["ai"])
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_chat.py -v
```

Expected: all 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/api/ai.py app/main.py tests/test_chat.py
git commit -m "feat: AI test-chat endpoint and AI run detail API"
```

---

### Task 14: Curator API

**Files:**
- Create: `app/curator/service.py`
- Create: `app/curator/router.py`
- Modify: `app/main.py`
- Create: `tests/test_curator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_curator.py
import pytest
from decimal import Decimal
from app.auth.service import create_access_token, hash_password
from app.db.models import (
    AIRun, Client, CuratorReview, Dialog, DialogStatus,
    ModelPricing, ReviewStatus, User, UserRole,
)


async def _setup(db):
    curator = User(email="c@c.ru", password_hash=hash_password("pw"), role=UserRole.curator)
    db.add(curator)
    client = Client(name="Test", source="test")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, current_status=DialogStatus.interested)
    db.add(dialog)
    await db.flush()
    ai_run = AIRun(
        dialog_id=dialog.id, provider="openai", model="gpt-4o",
        input_tokens=100, output_tokens=50, total_tokens=150,
        cost_amount=Decimal("0.001"), cost_currency="USD",
        confidence_score=Decimal("0.55"), need_curator=True,
        curator_reason="Low confidence",
        status_before="interested", status_after="interested",
        raw_response={},
    )
    db.add(ai_run)
    await db.flush()
    review = CuratorReview(
        dialog_id=dialog.id, ai_run_id=ai_run.id,
        status=ReviewStatus.pending,
        ai_draft="Draft reply",
        reason="Low confidence",
    )
    db.add(review)
    await db.commit()
    await db.refresh(curator)
    await db.refresh(review)
    return curator, review


async def test_list_reviews_requires_curator_role(client, db):
    tester = User(email="t@t.ru", password_hash=hash_password("pw"), role=UserRole.tester)
    db.add(tester)
    await db.commit()
    token = create_access_token(tester.id)
    resp = await client.get("/curator/reviews", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_list_reviews_returns_pending(client, db):
    curator, review = await _setup(db)
    token = create_access_token(curator.id)
    resp = await client.get("/curator/reviews", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(r["id"] == review.id for r in data)


async def test_approve_review(client, db):
    curator, review = await _setup(db)
    token = create_access_token(curator.id)
    resp = await client.post(
        f"/curator/reviews/{review.id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    await db.refresh(review)
    assert review.status == ReviewStatus.approved


async def test_edit_review(client, db):
    curator, review = await _setup(db)
    token = create_access_token(curator.id)
    resp = await client.post(
        f"/curator/reviews/{review.id}/edit",
        json={"final_text": "Edited reply by curator"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    await db.refresh(review)
    assert review.status == ReviewStatus.edited
    assert review.final_text == "Edited reply by curator"


async def test_reject_review(client, db):
    curator, review = await _setup(db)
    token = create_access_token(curator.id)
    resp = await client.post(
        f"/curator/reviews/{review.id}/reject",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    await db.refresh(review)
    assert review.status == ReviewStatus.rejected
```

- [ ] **Step 2: Create `app/curator/service.py`**

```python
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CuratorReview, ReviewStatus


async def resolve_review(
    db: AsyncSession,
    review: CuratorReview,
    status: ReviewStatus,
    curator_id: int,
    final_text: str | None = None,
) -> CuratorReview:
    review.status = status
    review.curator_id = curator_id
    review.resolved_at = datetime.utcnow()
    if final_text is not None:
        review.final_text = final_text
    await db.commit()
    await db.refresh(review)
    return review
```

- [ ] **Step 3: Create `app/curator/router.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.curator.service import resolve_review
from app.db.models import CuratorReview, ReviewStatus, User, UserRole
from app.db.session import get_db

router = APIRouter()
curator_required = require_role(UserRole.curator, UserRole.admin)


class ReviewOut(BaseModel):
    id: int
    dialog_id: int
    ai_run_id: int | None
    status: str
    ai_draft: str | None
    final_text: str | None
    reason: str | None
    curator_id: int | None
    created_at: str
    resolved_at: str | None


class EditRequest(BaseModel):
    final_text: str


def _to_out(r: CuratorReview) -> ReviewOut:
    return ReviewOut(
        id=r.id,
        dialog_id=r.dialog_id,
        ai_run_id=r.ai_run_id,
        status=r.status.value,
        ai_draft=r.ai_draft,
        final_text=r.final_text,
        reason=r.reason,
        curator_id=r.curator_id,
        created_at=r.created_at.isoformat(),
        resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
    )


@router.get("/reviews", response_model=list[ReviewOut])
async def list_reviews(
    status: str = "pending",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(curator_required),
):
    query = select(CuratorReview).order_by(desc(CuratorReview.created_at))
    if status:
        query = query.where(CuratorReview.status == ReviewStatus[status])
    result = await db.execute(query)
    return [_to_out(r) for r in result.scalars().all()]


@router.get("/reviews/{review_id}", response_model=ReviewOut)
async def get_review(
    review_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(curator_required),
):
    review = await db.get(CuratorReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return _to_out(review)


@router.post("/reviews/{review_id}/approve", response_model=ReviewOut)
async def approve_review(
    review_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(curator_required),
):
    review = await db.get(CuratorReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    review = await resolve_review(db, review, ReviewStatus.approved, current_user.id)
    return _to_out(review)


@router.post("/reviews/{review_id}/edit", response_model=ReviewOut)
async def edit_review(
    review_id: int,
    body: EditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(curator_required),
):
    review = await db.get(CuratorReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    review = await resolve_review(db, review, ReviewStatus.edited, current_user.id, body.final_text)
    return _to_out(review)


@router.post("/reviews/{review_id}/reject", response_model=ReviewOut)
async def reject_review(
    review_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(curator_required),
):
    review = await db.get(CuratorReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    review = await resolve_review(db, review, ReviewStatus.rejected, current_user.id)
    return _to_out(review)


@router.post("/reviews/{review_id}/takeover", response_model=ReviewOut)
async def takeover_review(
    review_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(curator_required),
):
    review = await db.get(CuratorReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    review = await resolve_review(db, review, ReviewStatus.takeover, current_user.id)
    return _to_out(review)
```

- [ ] **Step 4: Register in `app/main.py`**

```python
from app.curator.router import router as curator_router
app.include_router(curator_router, prefix="/curator", tags=["curator"])
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_curator.py -v
```

Expected: all 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add app/curator/ app/main.py tests/test_curator.py
git commit -m "feat: curator review API — list, approve, edit, reject, takeover"
```

---

### Task 15: Admin API + metrics

**Files:**
- Create: `app/api/admin.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create `app/api/admin.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from decimal import Decimal
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db.models import (
    AIRun, CuratorReview, Dialog, DialogStatus, FAQ,
    ModelPricing, PriceLadder, ReviewStatus, Script, User, UserRole,
)
from app.db.session import get_db

router = APIRouter()
admin_required = require_role(UserRole.admin)


# --- Scripts ---
class ScriptIn(BaseModel):
    name: str
    category: str | None = None
    stage: str | None = None
    objection_type: str | None = None
    body: str | None = None
    is_active: bool = True


class ScriptOut(BaseModel):
    id: int
    name: str
    category: str | None
    stage: str | None
    objection_type: str | None
    body: str | None
    is_active: bool


@router.get("/scripts", response_model=list[ScriptOut])
async def list_scripts(db: AsyncSession = Depends(get_db), _=Depends(admin_required)):
    result = await db.execute(select(Script).order_by(Script.stage, Script.name))
    return [ScriptOut(id=s.id, name=s.name, category=s.category, stage=s.stage,
                      objection_type=s.objection_type, body=s.body, is_active=s.is_active)
            for s in result.scalars().all()]


@router.put("/scripts/{script_id}", response_model=ScriptOut)
async def update_script(script_id: int, body: ScriptIn, db: AsyncSession = Depends(get_db), _=Depends(admin_required)):
    script = await db.get(Script, script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")
    for k, v in body.model_dump().items():
        setattr(script, k, v)
    await db.commit()
    await db.refresh(script)
    return ScriptOut(id=script.id, name=script.name, category=script.category, stage=script.stage,
                     objection_type=script.objection_type, body=script.body, is_active=script.is_active)


# --- FAQ ---
class FAQIn(BaseModel):
    key: str
    question: str
    answer: str
    is_active: bool = True


class FAQOut(BaseModel):
    id: int
    key: str
    question: str
    answer: str
    is_active: bool


@router.get("/faq", response_model=list[FAQOut])
async def list_faq(db: AsyncSession = Depends(get_db), _=Depends(admin_required)):
    result = await db.execute(select(FAQ).order_by(FAQ.key))
    return [FAQOut(id=f.id, key=f.key, question=f.question, answer=f.answer, is_active=f.is_active)
            for f in result.scalars().all()]


@router.put("/faq/{faq_id}", response_model=FAQOut)
async def update_faq(faq_id: int, body: FAQIn, db: AsyncSession = Depends(get_db), _=Depends(admin_required)):
    faq = await db.get(FAQ, faq_id)
    if faq is None:
        raise HTTPException(status_code=404, detail="FAQ not found")
    for k, v in body.model_dump().items():
        setattr(faq, k, v)
    await db.commit()
    await db.refresh(faq)
    return FAQOut(id=faq.id, key=faq.key, question=faq.question, answer=faq.answer, is_active=faq.is_active)


# --- Price ladder ---
class PriceOut(BaseModel):
    id: int
    size: str
    spreads_count: int
    regular_price: float
    minimum_price: float
    currency: str
    is_active: bool


class PriceIn(BaseModel):
    regular_price: float
    minimum_price: float
    is_active: bool = True


@router.get("/price-ladder", response_model=list[PriceOut])
async def list_prices(db: AsyncSession = Depends(get_db), _=Depends(admin_required)):
    result = await db.execute(select(PriceLadder).order_by(PriceLadder.spreads_count.desc(), PriceLadder.size))
    return [PriceOut(id=p.id, size=p.size, spreads_count=p.spreads_count,
                     regular_price=float(p.regular_price), minimum_price=float(p.minimum_price),
                     currency=p.currency, is_active=p.is_active)
            for p in result.scalars().all()]


@router.put("/price-ladder/{price_id}", response_model=PriceOut)
async def update_price(price_id: int, body: PriceIn, db: AsyncSession = Depends(get_db), _=Depends(admin_required)):
    price = await db.get(PriceLadder, price_id)
    if price is None:
        raise HTTPException(status_code=404, detail="Price not found")
    price.regular_price = Decimal(str(body.regular_price))
    price.minimum_price = Decimal(str(body.minimum_price))
    price.is_active = body.is_active
    await db.commit()
    await db.refresh(price)
    return PriceOut(id=price.id, size=price.size, spreads_count=price.spreads_count,
                    regular_price=float(price.regular_price), minimum_price=float(price.minimum_price),
                    currency=price.currency, is_active=price.is_active)


# --- Model pricing ---
class ModelPricingOut(BaseModel):
    id: int
    provider: str
    model: str
    input_price_per_1m: float
    output_price_per_1m: float
    currency: str
    is_active: bool


@router.get("/model-pricing", response_model=list[ModelPricingOut])
async def list_model_pricing(db: AsyncSession = Depends(get_db), _=Depends(admin_required)):
    result = await db.execute(select(ModelPricing).order_by(ModelPricing.provider, ModelPricing.model))
    return [ModelPricingOut(id=p.id, provider=p.provider, model=p.model,
                            input_price_per_1m=float(p.input_price_per_1m),
                            output_price_per_1m=float(p.output_price_per_1m),
                            currency=p.currency, is_active=p.is_active)
            for p in result.scalars().all()]


# --- Metrics ---
class MetricsOut(BaseModel):
    total_dialogs: int
    total_ai_runs: int
    runs_to_curator: int
    avg_confidence: float | None
    total_cost_usd: float
    pending_reviews: int
    dialogs_by_status: dict[str, int]


@router.get("/metrics", response_model=MetricsOut)
async def get_metrics(db: AsyncSession = Depends(get_db), _=Depends(admin_required)):
    total_dialogs = (await db.execute(select(func.count()).select_from(Dialog))).scalar()
    total_ai_runs = (await db.execute(select(func.count()).select_from(AIRun))).scalar()
    runs_to_curator = (await db.execute(
        select(func.count()).select_from(AIRun).where(AIRun.need_curator.is_(True))
    )).scalar()
    avg_confidence = (await db.execute(select(func.avg(AIRun.confidence_score)))).scalar()
    total_cost = (await db.execute(select(func.sum(AIRun.cost_amount)))).scalar()
    pending_reviews = (await db.execute(
        select(func.count()).select_from(CuratorReview).where(CuratorReview.status == ReviewStatus.pending)
    )).scalar()

    status_counts = {}
    for status in DialogStatus:
        count = (await db.execute(
            select(func.count()).select_from(Dialog).where(Dialog.current_status == status)
        )).scalar()
        if count:
            status_counts[status.value] = count

    return MetricsOut(
        total_dialogs=total_dialogs or 0,
        total_ai_runs=total_ai_runs or 0,
        runs_to_curator=runs_to_curator or 0,
        avg_confidence=float(avg_confidence) if avg_confidence else None,
        total_cost_usd=float(total_cost) if total_cost else 0.0,
        pending_reviews=pending_reviews or 0,
        dialogs_by_status=status_counts,
    )
```

- [ ] **Step 2: Register in `app/main.py`**

```python
from app.api.admin import router as admin_router
app.include_router(admin_router, prefix="/admin", tags=["admin"])
```

- [ ] **Step 3: Quick smoke test**

```bash
python -c "from app.api.admin import router; print('admin router OK')"
```

Expected: `admin router OK`

- [ ] **Step 4: Commit**

```bash
git add app/api/admin.py app/main.py
git commit -m "feat: admin API — scripts, FAQ, prices, model pricing, metrics"
```

---

### Task 16: Vue frontend scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/api/client.ts`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "monroe-ai-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "axios": "^1.7.0",
    "pinia": "^2.1.7",
    "vue": "^3.4.0",
    "vue-router": "^4.3.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "vue-tsc": "^2.0.0"
  }
}
```

- [ ] **Step 2: Create `frontend/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/ai': 'http://localhost:8000',
      '/dialogs': 'http://localhost:8000',
      '/curator': 'http://localhost:8000',
      '/admin': 'http://localhost:8000',
      '/crm': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
```

- [ ] **Step 3: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Monro AI Layer</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 4: Create `frontend/tailwind.config.js`**

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  theme: { extend: {} },
  plugins: [],
}
```

- [ ] **Step 5: Create `frontend/postcss.config.js`**

```javascript
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
}
```

- [ ] **Step 6: Create `frontend/src/main.ts`**

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

createApp(App).use(createPinia()).use(router).mount('#app')
```

- [ ] **Step 7: Create `frontend/src/style.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 8: Create `frontend/src/App.vue`**

```vue
<template>
  <router-view />
</template>
```

- [ ] **Step 9: Create `frontend/src/router/index.ts`**

```typescript
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', component: () => import('../pages/Login.vue') },
  { path: '/register', component: () => import('../pages/Register.vue') },
  {
    path: '/tester/chat',
    component: () => import('../pages/TesterChat.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/tester/chat/:dialogId',
    component: () => import('../pages/TesterChat.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/curator',
    component: () => import('../pages/CuratorDashboard.vue'),
    meta: { requiresAuth: true, roles: ['curator', 'admin'] },
  },
  {
    path: '/curator/review/:reviewId',
    component: () => import('../pages/CuratorReview.vue'),
    meta: { requiresAuth: true, roles: ['curator', 'admin'] },
  },
  {
    path: '/admin',
    component: () => import('../pages/AdminSettings.vue'),
    meta: { requiresAuth: true, roles: ['admin'] },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.token) {
    next('/login')
  } else {
    next()
  }
})

export default router
```

- [ ] **Step 10: Create `frontend/src/api/client.ts`**

```typescript
import axios from 'axios'

const api = axios.create({ baseURL: '/' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api
```

- [ ] **Step 11: Install deps + verify dev server starts**

```bash
cd frontend && npm install && npm run dev &
# Wait 3 seconds, then curl
sleep 3 && curl -s http://localhost:5173 | head -5
```

Expected: HTML with `<div id="app">`.

- [ ] **Step 12: Commit**

```bash
cd ..
git add frontend/
git commit -m "feat: Vue 3 frontend scaffold — Vite, router, Pinia, Tailwind, axios client"
```

---

### Task 17: Auth store + Login + Register pages

**Files:**
- Create: `frontend/src/stores/auth.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/pages/Login.vue`
- Create: `frontend/src/pages/Register.vue`

- [ ] **Step 1: Create `frontend/src/stores/auth.ts`**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface AuthUser {
  id: number
  email: string
  role: string
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const user = ref<AuthUser | null>(null)

  function setToken(t: string) {
    token.value = t
    localStorage.setItem('token', t)
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
  }

  return { token, user, setToken, logout }
})
```

- [ ] **Step 2: Create `frontend/src/api/auth.ts`**

```typescript
import api from './client'

export async function login(email: string, password: string) {
  const resp = await api.post('/auth/login', { email, password })
  return resp.data as { access_token: string; token_type: string }
}

export async function register(email: string, password: string, role = 'tester') {
  const resp = await api.post('/auth/register', { email, password, role })
  return resp.data
}

export async function getMe() {
  const resp = await api.get('/auth/me')
  return resp.data
}
```

- [ ] **Step 3: Create `frontend/src/pages/Login.vue`**

```vue
<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50">
    <div class="bg-white p-8 rounded shadow w-full max-w-sm">
      <h1 class="text-2xl font-bold mb-6 text-center">Monro AI Layer</h1>
      <form @submit.prevent="submit">
        <div class="mb-4">
          <label class="block text-sm font-medium mb-1">Email</label>
          <input v-model="email" type="email" required class="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div class="mb-6">
          <label class="block text-sm font-medium mb-1">Пароль</label>
          <input v-model="password" type="password" required class="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <button type="submit" :disabled="loading" class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:opacity-50">
          {{ loading ? 'Вход...' : 'Войти' }}
        </button>
        <p v-if="error" class="mt-3 text-red-500 text-sm text-center">{{ error }}</p>
      </form>
      <p class="mt-4 text-center text-sm">
        Нет аккаунта? <router-link to="/register" class="text-blue-600 hover:underline">Регистрация</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login, getMe } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    const data = await login(email.value, password.value)
    auth.setToken(data.access_token)
    auth.user = await getMe()
    const role = auth.user?.role
    if (role === 'curator' || role === 'admin') router.push('/curator')
    else router.push('/tester/chat')
  } catch {
    error.value = 'Неверный email или пароль'
  } finally {
    loading.value = false
  }
}
</script>
```

- [ ] **Step 4: Create `frontend/src/pages/Register.vue`**

```vue
<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50">
    <div class="bg-white p-8 rounded shadow w-full max-w-sm">
      <h1 class="text-2xl font-bold mb-6 text-center">Регистрация</h1>
      <form @submit.prevent="submit">
        <div class="mb-4">
          <label class="block text-sm font-medium mb-1">Email</label>
          <input v-model="email" type="email" required class="w-full border rounded px-3 py-2" />
        </div>
        <div class="mb-4">
          <label class="block text-sm font-medium mb-1">Пароль</label>
          <input v-model="password" type="password" required class="w-full border rounded px-3 py-2" />
        </div>
        <div class="mb-6">
          <label class="block text-sm font-medium mb-1">Роль</label>
          <select v-model="role" class="w-full border rounded px-3 py-2">
            <option value="tester">Тестировщик</option>
            <option value="curator">Куратор</option>
          </select>
        </div>
        <button type="submit" :disabled="loading" class="w-full bg-green-600 text-white py-2 rounded hover:bg-green-700 disabled:opacity-50">
          {{ loading ? 'Создание...' : 'Создать аккаунт' }}
        </button>
        <p v-if="error" class="mt-3 text-red-500 text-sm text-center">{{ error }}</p>
      </form>
      <p class="mt-4 text-center text-sm">
        Уже есть аккаунт? <router-link to="/login" class="text-blue-600 hover:underline">Войти</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { register, login, getMe } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const role = ref('tester')
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await register(email.value, password.value, role.value)
    const data = await login(email.value, password.value)
    auth.setToken(data.access_token)
    auth.user = await getMe()
    router.push(role.value === 'curator' ? '/curator' : '/tester/chat')
  } catch {
    error.value = 'Ошибка регистрации'
  } finally {
    loading.value = false
  }
}
</script>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/auth.ts frontend/src/api/auth.ts frontend/src/pages/Login.vue frontend/src/pages/Register.vue
git commit -m "feat: auth store, Login and Register pages"
```

---

### Task 18: TesterChat page

**Files:**
- Create: `frontend/src/stores/chat.ts`
- Create: `frontend/src/api/ai.ts`
- Create: `frontend/src/components/MessageBubble.vue`
- Create: `frontend/src/components/MetadataStrip.vue`
- Create: `frontend/src/pages/TesterChat.vue`

- [ ] **Step 1: Create `frontend/src/api/ai.ts`**

```typescript
import api from './client'

export interface TestChatResponse {
  ai_run_id: number
  dialog_id: number
  client_reply: string
  status_before: string
  status_after: string
  funnel_stage: string
  objection_type: string | null
  selected_script: string | null
  price_offer: number | null
  need_curator: boolean
  curator_reason: string | null
  confidence_score: number
  internal_note: string
  cost_amount: number | null
  cost_currency: string
}

export async function sendTestChat(dialogId: number | null, text: string): Promise<TestChatResponse> {
  const resp = await api.post('/ai/test-chat', { dialog_id: dialogId, text })
  return resp.data
}

export async function getDialogMessages(dialogId: number) {
  const resp = await api.get(`/dialogs/${dialogId}/messages`)
  return resp.data as Array<{ id: number; role: string; text: string; created_at: string }>
}
```

- [ ] **Step 2: Create `frontend/src/stores/chat.ts`**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { TestChatResponse } from '../api/ai'

export interface ChatMessage {
  id?: number
  role: 'client' | 'ai'
  text: string
  created_at?: string
}

export interface LastAIMetadata {
  model: string
  cost_amount: number | null
  cost_currency: string
  confidence_score: number
  selected_script: string | null
  need_curator: boolean
  status_after: string
  funnel_stage: string
}

export const useChatStore = defineStore('chat', () => {
  const dialogId = ref<number | null>(null)
  const messages = ref<ChatMessage[]>([])
  const lastMeta = ref<LastAIMetadata | null>(null)
  const loading = ref(false)

  function setDialog(id: number) {
    dialogId.value = id
  }

  function addMessage(msg: ChatMessage) {
    messages.value.push(msg)
  }

  function setMeta(resp: TestChatResponse) {
    lastMeta.value = {
      model: 'gpt-4o',
      cost_amount: resp.cost_amount,
      cost_currency: resp.cost_currency,
      confidence_score: resp.confidence_score,
      selected_script: resp.selected_script,
      need_curator: resp.need_curator,
      status_after: resp.status_after,
      funnel_stage: resp.funnel_stage,
    }
    dialogId.value = resp.dialog_id
  }

  function reset() {
    dialogId.value = null
    messages.value = []
    lastMeta.value = null
  }

  return { dialogId, messages, lastMeta, loading, setDialog, addMessage, setMeta, reset }
})
```

- [ ] **Step 3: Create `frontend/src/components/MessageBubble.vue`**

```vue
<template>
  <div :class="['flex mb-3', isAI ? 'justify-start' : 'justify-end']">
    <div
      :class="[
        'max-w-xs lg:max-w-md px-4 py-2 rounded-lg text-sm whitespace-pre-wrap',
        isAI
          ? 'bg-gray-100 text-gray-900'
          : 'bg-blue-600 text-white',
      ]"
    >
      <span class="block text-xs opacity-60 mb-1">{{ isAI ? 'AI-продавец' : 'Клиент' }}</span>
      {{ text }}
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ role: string; text: string }>()
const isAI = defineProps<{ role: string; text: string }>().role === 'ai'
</script>
```

- [ ] **Step 4: Create `frontend/src/components/MetadataStrip.vue`**

```vue
<template>
  <div class="bg-gray-50 border-l p-4 text-sm space-y-2 h-full overflow-y-auto">
    <h3 class="font-semibold text-gray-700 mb-3">Метаданные ответа</h3>
    <template v-if="meta">
      <div class="flex justify-between">
        <span class="text-gray-500">Статус</span>
        <span class="font-medium">{{ meta.status_after }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-gray-500">Этап воронки</span>
        <span class="font-medium">{{ meta.funnel_stage }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-gray-500">Confidence</span>
        <span :class="meta.confidence_score >= 0.72 ? 'text-green-600' : 'text-red-600'" class="font-medium">
          {{ (meta.confidence_score * 100).toFixed(0) }}%
        </span>
      </div>
      <div class="flex justify-between">
        <span class="text-gray-500">Скрипт</span>
        <span class="font-medium text-right max-w-32 truncate">{{ meta.selected_script || '—' }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-gray-500">Стоимость</span>
        <span class="font-medium">
          {{ meta.cost_amount != null ? `$${meta.cost_amount.toFixed(5)}` : '—' }}
        </span>
      </div>
      <div class="flex justify-between">
        <span class="text-gray-500">Куратор</span>
        <span :class="meta.need_curator ? 'text-red-600 font-semibold' : 'text-green-600'">
          {{ meta.need_curator ? 'Нужен' : 'Нет' }}
        </span>
      </div>
    </template>
    <p v-else class="text-gray-400 text-center mt-8">Метаданные появятся после первого ответа</p>
  </div>
</template>

<script setup lang="ts">
import type { LastAIMetadata } from '../stores/chat'
defineProps<{ meta: LastAIMetadata | null }>()
</script>
```

- [ ] **Step 5: Create `frontend/src/pages/TesterChat.vue`**

```vue
<template>
  <div class="flex h-screen">
    <!-- Sidebar -->
    <div class="w-64 bg-gray-800 text-white flex flex-col p-4">
      <h2 class="text-lg font-bold mb-4">Monro AI Layer</h2>
      <button @click="newDialog" class="bg-blue-600 rounded px-3 py-2 text-sm mb-4 hover:bg-blue-700">
        + Новый диалог
      </button>
      <div class="text-sm text-gray-400">
        <p v-if="chat.dialogId">Dialog #{{ chat.dialogId }}</p>
        <p v-else>Новый чат</p>
      </div>
      <div class="mt-auto">
        <button @click="auth.logout(); router.push('/login')" class="text-gray-400 text-sm hover:text-white">
          Выйти
        </button>
      </div>
    </div>

    <!-- Chat area -->
    <div class="flex flex-1 overflow-hidden">
      <div class="flex flex-col flex-1">
        <!-- Messages -->
        <div ref="messagesEl" class="flex-1 overflow-y-auto p-4">
          <MessageBubble v-for="(msg, i) in chat.messages" :key="i" :role="msg.role" :text="msg.text" />
          <div v-if="chat.loading" class="flex justify-start mb-3">
            <div class="bg-gray-100 px-4 py-2 rounded-lg text-sm text-gray-500">Печатаю...</div>
          </div>
        </div>

        <!-- Input -->
        <div class="border-t p-4 flex gap-2">
          <input
            v-model="inputText"
            @keydown.enter.prevent="send"
            placeholder="Напишите сообщение как клиент..."
            class="flex-1 border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            :disabled="chat.loading"
          />
          <button @click="send" :disabled="chat.loading || !inputText.trim()" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50">
            Отправить
          </button>
        </div>
      </div>

      <!-- Metadata strip -->
      <div class="w-64 border-l">
        <MetadataStrip :meta="chat.lastMeta" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useChatStore } from '../stores/chat'
import { useAuthStore } from '../stores/auth'
import { sendTestChat, getDialogMessages } from '../api/ai'
import MessageBubble from '../components/MessageBubble.vue'
import MetadataStrip from '../components/MetadataStrip.vue'

const router = useRouter()
const route = useRoute()
const chat = useChatStore()
const auth = useAuthStore()
const inputText = ref('')
const messagesEl = ref<HTMLElement>()

onMounted(async () => {
  const dialogId = route.params.dialogId ? Number(route.params.dialogId) : null
  if (dialogId) {
    chat.setDialog(dialogId)
    const msgs = await getDialogMessages(dialogId)
    chat.messages = msgs.map(m => ({ role: m.role as 'client' | 'ai', text: m.text, id: m.id }))
  }
})

function newDialog() {
  chat.reset()
  router.push('/tester/chat')
}

async function send() {
  const text = inputText.value.trim()
  if (!text) return
  inputText.value = ''
  chat.addMessage({ role: 'client', text })
  chat.loading = true
  await nextTick()
  messagesEl.value?.scrollTo({ top: messagesEl.value.scrollHeight, behavior: 'smooth' })

  try {
    const resp = await sendTestChat(chat.dialogId, text)
    chat.addMessage({ role: 'ai', text: resp.client_reply })
    chat.setMeta(resp)
    router.replace(`/tester/chat/${resp.dialog_id}`)
  } catch (e: any) {
    chat.addMessage({ role: 'ai', text: `Ошибка: ${e.message}` })
  } finally {
    chat.loading = false
    await nextTick()
    messagesEl.value?.scrollTo({ top: messagesEl.value.scrollHeight, behavior: 'smooth' })
  }
}
</script>
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/chat.ts frontend/src/api/ai.ts frontend/src/components/ frontend/src/pages/TesterChat.vue
git commit -m "feat: TesterChat page with message history and AI metadata strip"
```

---

### Task 19: Curator pages

**Files:**
- Create: `frontend/src/stores/curator.ts`
- Create: `frontend/src/api/curator.ts`
- Create: `frontend/src/pages/CuratorDashboard.vue`
- Create: `frontend/src/pages/CuratorReview.vue`

- [ ] **Step 1: Create `frontend/src/api/curator.ts`**

```typescript
import api from './client'

export interface ReviewOut {
  id: number
  dialog_id: number
  ai_run_id: number | null
  status: string
  ai_draft: string | null
  final_text: string | null
  reason: string | null
  curator_id: number | null
  created_at: string
  resolved_at: string | null
}

export async function listReviews(status = 'pending'): Promise<ReviewOut[]> {
  const resp = await api.get('/curator/reviews', { params: { status } })
  return resp.data
}

export async function getReview(id: number): Promise<ReviewOut> {
  const resp = await api.get(`/curator/reviews/${id}`)
  return resp.data
}

export async function approveReview(id: number): Promise<ReviewOut> {
  const resp = await api.post(`/curator/reviews/${id}/approve`)
  return resp.data
}

export async function editReview(id: number, finalText: string): Promise<ReviewOut> {
  const resp = await api.post(`/curator/reviews/${id}/edit`, { final_text: finalText })
  return resp.data
}

export async function rejectReview(id: number): Promise<ReviewOut> {
  const resp = await api.post(`/curator/reviews/${id}/reject`)
  return resp.data
}

export async function takeoverReview(id: number): Promise<ReviewOut> {
  const resp = await api.post(`/curator/reviews/${id}/takeover`)
  return resp.data
}
```

- [ ] **Step 2: Create `frontend/src/stores/curator.ts`**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ReviewOut } from '../api/curator'

export const useCuratorStore = defineStore('curator', () => {
  const reviews = ref<ReviewOut[]>([])
  const loading = ref(false)
  return { reviews, loading }
})
```

- [ ] **Step 3: Create `frontend/src/pages/CuratorDashboard.vue`**

```vue
<template>
  <div class="min-h-screen bg-gray-50">
    <nav class="bg-white border-b px-6 py-3 flex items-center justify-between">
      <h1 class="font-bold text-lg">Панель куратора</h1>
      <div class="flex gap-4 text-sm">
        <button @click="filterStatus = 'pending'; load()" :class="filterStatus === 'pending' ? 'text-blue-600 font-semibold' : 'text-gray-500'">Ожидают ({{ pendingCount }})</button>
        <button @click="filterStatus = ''; load()" :class="filterStatus === '' ? 'text-blue-600 font-semibold' : 'text-gray-500'">Все</button>
        <button @click="auth.logout(); router.push('/login')" class="text-gray-400 hover:text-gray-700">Выйти</button>
      </div>
    </nav>

    <div class="p-6">
      <div v-if="loading" class="text-center text-gray-400 py-16">Загрузка...</div>
      <div v-else-if="reviews.length === 0" class="text-center text-gray-400 py-16">Нет задач для проверки</div>
      <table v-else class="w-full bg-white rounded shadow text-sm">
        <thead class="bg-gray-100 text-left">
          <tr>
            <th class="px-4 py-3">ID</th>
            <th class="px-4 py-3">Диалог</th>
            <th class="px-4 py-3">Статус</th>
            <th class="px-4 py-3">Причина</th>
            <th class="px-4 py-3">Создан</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in reviews" :key="r.id" class="border-t hover:bg-gray-50">
            <td class="px-4 py-3">{{ r.id }}</td>
            <td class="px-4 py-3">#{{ r.dialog_id }}</td>
            <td class="px-4 py-3">
              <span :class="r.status === 'pending' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'" class="px-2 py-0.5 rounded text-xs font-medium">
                {{ r.status }}
              </span>
            </td>
            <td class="px-4 py-3 max-w-xs truncate">{{ r.reason || '—' }}</td>
            <td class="px-4 py-3 text-gray-400">{{ new Date(r.created_at).toLocaleString('ru') }}</td>
            <td class="px-4 py-3">
              <router-link :to="`/curator/review/${r.id}`" class="text-blue-600 hover:underline">Открыть</router-link>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listReviews, type ReviewOut } from '../api/curator'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const reviews = ref<ReviewOut[]>([])
const loading = ref(false)
const filterStatus = ref('pending')
const pendingCount = computed(() => reviews.value.filter(r => r.status === 'pending').length)

async function load() {
  loading.value = true
  try {
    reviews.value = await listReviews(filterStatus.value)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
```

- [ ] **Step 4: Create `frontend/src/pages/CuratorReview.vue`**

```vue
<template>
  <div class="min-h-screen bg-gray-50 flex flex-col">
    <nav class="bg-white border-b px-6 py-3 flex items-center gap-4">
      <router-link to="/curator" class="text-blue-600 hover:underline text-sm">← Назад</router-link>
      <h1 class="font-bold text-lg">Проверка #{{ reviewId }}</h1>
    </nav>

    <div v-if="loading" class="flex-1 flex items-center justify-center text-gray-400">Загрузка...</div>
    <div v-else-if="review" class="flex flex-1 overflow-hidden">

      <!-- Message history -->
      <div class="flex-1 p-6 overflow-y-auto">
        <h3 class="font-semibold mb-3 text-gray-700">История диалога #{{ review.dialog_id }}</h3>
        <div v-for="(msg, i) in messages" :key="i"
          :class="['mb-3 p-3 rounded', msg.role === 'client' ? 'bg-blue-50 text-right' : 'bg-gray-50']">
          <span class="text-xs text-gray-400 block mb-1">{{ msg.role === 'client' ? 'Клиент' : 'AI-продавец' }}</span>
          {{ msg.text }}
        </div>
      </div>

      <!-- Review panel -->
      <div class="w-80 border-l bg-white p-6 flex flex-col gap-4">
        <div>
          <p class="text-xs text-gray-500 mb-1">Причина передачи куратору</p>
          <p class="text-sm bg-yellow-50 border border-yellow-200 rounded p-2">{{ review.reason || '—' }}</p>
        </div>

        <div v-if="review.status === 'pending'">
          <p class="text-xs text-gray-500 mb-1">Черновик AI</p>
          <textarea v-model="editedText" rows="6" class="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div v-else>
          <p class="text-xs text-gray-500 mb-1">Финальный текст</p>
          <p class="text-sm bg-green-50 border border-green-200 rounded p-2 whitespace-pre-wrap">{{ review.final_text || review.ai_draft }}</p>
          <p class="text-xs text-green-600 mt-1 font-medium">Статус: {{ review.status }}</p>
        </div>

        <div v-if="review.status === 'pending'" class="flex flex-col gap-2">
          <button @click="action('approve')" class="bg-green-600 text-white rounded py-2 text-sm hover:bg-green-700">Одобрить</button>
          <button @click="action('edit')" class="bg-blue-600 text-white rounded py-2 text-sm hover:bg-blue-700">Редактировать и отправить</button>
          <button @click="action('reject')" class="bg-gray-200 text-gray-700 rounded py-2 text-sm hover:bg-gray-300">Отклонить</button>
          <button @click="action('takeover')" class="bg-orange-500 text-white rounded py-2 text-sm hover:bg-orange-600">Взять на себя</button>
        </div>

        <p v-if="actionError" class="text-red-500 text-sm">{{ actionError }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getReview, approveReview, editReview, rejectReview, takeoverReview, type ReviewOut } from '../api/curator'
import { getDialogMessages } from '../api/ai'

const route = useRoute()
const router = useRouter()
const reviewId = Number(route.params.reviewId)
const review = ref<ReviewOut | null>(null)
const messages = ref<Array<{ role: string; text: string }>>([])
const editedText = ref('')
const loading = ref(false)
const actionError = ref('')

onMounted(async () => {
  loading.value = true
  try {
    review.value = await getReview(reviewId)
    editedText.value = review.value.ai_draft || ''
    messages.value = await getDialogMessages(review.value.dialog_id)
  } finally {
    loading.value = false
  }
})

async function action(type: 'approve' | 'edit' | 'reject' | 'takeover') {
  actionError.value = ''
  try {
    if (type === 'approve') await approveReview(reviewId)
    else if (type === 'edit') await editReview(reviewId, editedText.value)
    else if (type === 'reject') await rejectReview(reviewId)
    else await takeoverReview(reviewId)
    router.push('/curator')
  } catch {
    actionError.value = 'Ошибка. Попробуйте ещё раз.'
  }
}
</script>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/curator.ts frontend/src/api/curator.ts frontend/src/pages/CuratorDashboard.vue frontend/src/pages/CuratorReview.vue
git commit -m "feat: curator dashboard and review pages"
```

---

### Task 20: Admin settings page

**Files:**
- Create: `frontend/src/api/admin.ts`
- Create: `frontend/src/stores/admin.ts`
- Create: `frontend/src/pages/AdminSettings.vue`

- [ ] **Step 1: Create `frontend/src/api/admin.ts`**

```typescript
import api from './client'

export async function getScripts() { return (await api.get('/admin/scripts')).data }
export async function updateScript(id: number, data: any) { return (await api.put(`/admin/scripts/${id}`, data)).data }
export async function getFaq() { return (await api.get('/admin/faq')).data }
export async function updateFaq(id: number, data: any) { return (await api.put(`/admin/faq/${id}`, data)).data }
export async function getPrices() { return (await api.get('/admin/price-ladder')).data }
export async function updatePrice(id: number, data: any) { return (await api.put(`/admin/price-ladder/${id}`, data)).data }
export async function getModelPricing() { return (await api.get('/admin/model-pricing')).data }
export async function getMetrics() { return (await api.get('/admin/metrics')).data }
```

- [ ] **Step 2: Create `frontend/src/stores/admin.ts`**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAdminStore = defineStore('admin', () => {
  const activeTab = ref<'prices' | 'scripts' | 'faq' | 'models' | 'metrics'>('metrics')
  return { activeTab }
})
```

- [ ] **Step 3: Create `frontend/src/pages/AdminSettings.vue`**

```vue
<template>
  <div class="min-h-screen bg-gray-50">
    <nav class="bg-white border-b px-6 py-3 flex items-center gap-6">
      <h1 class="font-bold text-lg">Администрирование</h1>
      <div class="flex gap-4 text-sm">
        <button v-for="tab in tabs" :key="tab.key"
          @click="activeTab = tab.key"
          :class="activeTab === tab.key ? 'text-blue-600 font-semibold border-b-2 border-blue-600' : 'text-gray-500'">
          {{ tab.label }}
        </button>
      </div>
    </nav>

    <div class="p-6">
      <!-- Metrics -->
      <div v-if="activeTab === 'metrics'" class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <template v-if="metrics">
          <div class="bg-white rounded shadow p-4">
            <p class="text-sm text-gray-500">Всего диалогов</p>
            <p class="text-2xl font-bold">{{ metrics.total_dialogs }}</p>
          </div>
          <div class="bg-white rounded shadow p-4">
            <p class="text-sm text-gray-500">AI-ответов</p>
            <p class="text-2xl font-bold">{{ metrics.total_ai_runs }}</p>
          </div>
          <div class="bg-white rounded shadow p-4">
            <p class="text-sm text-gray-500">Передано куратору</p>
            <p class="text-2xl font-bold">{{ metrics.runs_to_curator }}</p>
          </div>
          <div class="bg-white rounded shadow p-4">
            <p class="text-sm text-gray-500">Ожидают проверки</p>
            <p class="text-2xl font-bold text-red-600">{{ metrics.pending_reviews }}</p>
          </div>
          <div class="bg-white rounded shadow p-4">
            <p class="text-sm text-gray-500">Средний confidence</p>
            <p class="text-2xl font-bold">{{ metrics.avg_confidence != null ? (metrics.avg_confidence * 100).toFixed(0) + '%' : '—' }}</p>
          </div>
          <div class="bg-white rounded shadow p-4">
            <p class="text-sm text-gray-500">Суммарные затраты</p>
            <p class="text-2xl font-bold">${{ metrics.total_cost_usd.toFixed(4) }}</p>
          </div>
        </template>
        <div v-else class="col-span-4 text-gray-400 text-center py-8">Загрузка метрик...</div>
      </div>

      <!-- Prices -->
      <div v-else-if="activeTab === 'prices'">
        <table class="w-full bg-white rounded shadow text-sm">
          <thead class="bg-gray-100 text-left">
            <tr>
              <th class="px-4 py-3">Размер</th>
              <th class="px-4 py-3">Разворотов</th>
              <th class="px-4 py-3">Обычная цена</th>
              <th class="px-4 py-3">Мин. цена</th>
              <th class="px-4 py-3">Активна</th>
              <th class="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in prices" :key="p.id" class="border-t">
              <td class="px-4 py-2">{{ p.size }}</td>
              <td class="px-4 py-2">{{ p.spreads_count }}</td>
              <td class="px-4 py-2">
                <input v-model.number="p.regular_price" type="number" class="border rounded px-2 py-1 w-24" />
              </td>
              <td class="px-4 py-2">
                <input v-model.number="p.minimum_price" type="number" class="border rounded px-2 py-1 w-24" />
              </td>
              <td class="px-4 py-2">
                <input v-model="p.is_active" type="checkbox" />
              </td>
              <td class="px-4 py-2">
                <button @click="savePrice(p)" class="text-blue-600 text-xs hover:underline">Сохранить</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Scripts -->
      <div v-else-if="activeTab === 'scripts'" class="space-y-4">
        <div v-for="s in scripts" :key="s.id" class="bg-white rounded shadow p-4">
          <div class="flex items-center gap-2 mb-2">
            <span class="font-medium text-sm">{{ s.name }}</span>
            <span class="text-xs text-gray-400">{{ s.stage }}</span>
            <span v-if="s.objection_type" class="text-xs bg-orange-100 text-orange-700 px-1 rounded">{{ s.objection_type }}</span>
          </div>
          <textarea v-model="s.body" rows="3" class="w-full border rounded px-2 py-1 text-sm focus:outline-none" />
          <button @click="saveScript(s)" class="mt-2 text-blue-600 text-xs hover:underline">Сохранить</button>
        </div>
      </div>

      <!-- FAQ -->
      <div v-else-if="activeTab === 'faq'" class="space-y-4">
        <div v-for="f in faq" :key="f.id" class="bg-white rounded shadow p-4">
          <p class="text-sm font-medium mb-1">{{ f.question }}</p>
          <p class="text-xs text-gray-400 mb-2">Ключ: {{ f.key }}</p>
          <textarea v-model="f.answer" rows="3" class="w-full border rounded px-2 py-1 text-sm focus:outline-none" />
          <button @click="saveFaq(f)" class="mt-2 text-blue-600 text-xs hover:underline">Сохранить</button>
        </div>
      </div>

      <!-- Models -->
      <div v-else-if="activeTab === 'models'">
        <table class="w-full bg-white rounded shadow text-sm">
          <thead class="bg-gray-100 text-left">
            <tr>
              <th class="px-4 py-3">Provider</th>
              <th class="px-4 py-3">Model</th>
              <th class="px-4 py-3">Input $/1M</th>
              <th class="px-4 py-3">Output $/1M</th>
              <th class="px-4 py-3">Активна</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in modelPricing" :key="m.id" class="border-t">
              <td class="px-4 py-2">{{ m.provider }}</td>
              <td class="px-4 py-2 font-mono text-xs">{{ m.model }}</td>
              <td class="px-4 py-2">${{ m.input_price_per_1m }}</td>
              <td class="px-4 py-2">${{ m.output_price_per_1m }}</td>
              <td class="px-4 py-2"><input type="checkbox" :checked="m.is_active" disabled /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { getScripts, updateScript, getFaq, updateFaq, getPrices, updatePrice, getModelPricing, getMetrics } from '../api/admin'

const tabs = [
  { key: 'metrics', label: 'Метрики' },
  { key: 'prices', label: 'Цены' },
  { key: 'scripts', label: 'Скрипты' },
  { key: 'faq', label: 'FAQ' },
  { key: 'models', label: 'Модели' },
] as const

type Tab = typeof tabs[number]['key']
const activeTab = ref<Tab>('metrics')
const metrics = ref<any>(null)
const prices = ref<any[]>([])
const scripts = ref<any[]>([])
const faq = ref<any[]>([])
const modelPricing = ref<any[]>([])

async function load(tab: Tab) {
  if (tab === 'metrics' && !metrics.value) metrics.value = await getMetrics()
  if (tab === 'prices' && !prices.value.length) prices.value = await getPrices()
  if (tab === 'scripts' && !scripts.value.length) scripts.value = await getScripts()
  if (tab === 'faq' && !faq.value.length) faq.value = await getFaq()
  if (tab === 'models' && !modelPricing.value.length) modelPricing.value = await getModelPricing()
}

onMounted(() => load(activeTab.value))
watch(activeTab, (t) => load(t))

async function savePrice(p: any) { await updatePrice(p.id, { regular_price: p.regular_price, minimum_price: p.minimum_price, is_active: p.is_active }) }
async function saveScript(s: any) { await updateScript(s.id, { name: s.name, category: s.category, stage: s.stage, objection_type: s.objection_type, body: s.body, is_active: s.is_active }) }
async function saveFaq(f: any) { await updateFaq(f.id, { key: f.key, question: f.question, answer: f.answer, is_active: f.is_active }) }
</script>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/admin.ts frontend/src/stores/admin.ts frontend/src/pages/AdminSettings.vue
git commit -m "feat: admin settings page — metrics, prices, scripts, FAQ, models"
```

---

### Task 21: Objection behavior tests

**Files:**
- Create: `tests/test_objections.py`

- [ ] **Step 1: Create `tests/test_objections.py`**

```python
"""
These tests verify AI behavior rules without calling real LLM.
They mock Runner.run and assert the runner correctly enforces
business rules on the AgentOutput (e.g., no auto-pings, curator triggers).
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.schemas import AgentOutput
from app.ai.runner import run_agent_for_dialog
from app.db.models import Client, CuratorReview, Dialog, DialogStatus, ModelPricing, PromptVersion


async def _setup_db(db):
    client = Client(name="Test", source="test")
    db.add(client)
    await db.flush()
    dialog = Dialog(client_id=client.id, current_status=DialogStatus.interested)
    db.add(dialog)
    db.add(ModelPricing(
        provider="openai", model="gpt-4o",
        input_price_per_1m=Decimal("2.50"), output_price_per_1m=Decimal("10.00"),
    ))
    db.add(PromptVersion(name="sales_agent_v1", version="1.0", content="p", is_active=True))
    db.add(PromptVersion(name="objection_agent_v1", version="1.0", content="p", is_active=True))
    await db.commit()
    await db.refresh(dialog)
    await db.refresh(client)
    return dialog, client


def _mock_result(output: AgentOutput) -> MagicMock:
    r = MagicMock()
    r.final_output = output
    r.usage = MagicMock(input_tokens=100, output_tokens=50)
    return r


async def test_low_confidence_triggers_curator(db):
    """confidence < 0.72 must create curator review regardless of need_curator flag."""
    dialog, client = await _setup_db(db)
    output = AgentOutput(
        client_reply="Подскажите, пожалуйста...",
        status_before="interested", status_after="interested",
        funnel_stage="greeting", confidence_score=0.60,
        need_curator=False, internal_note="low conf",
    )
    with patch("app.ai.runner.Runner.run", new_callable=AsyncMock) as m:
        m.return_value = _mock_result(output)
        ai_run = await run_agent_for_dialog(db, dialog.id, client.id, "Дорого")

    from sqlalchemy import select
    reviews = (await db.execute(select(CuratorReview).where(CuratorReview.dialog_id == dialog.id))).scalars().all()
    assert len(reviews) == 1
    assert "0.60" in reviews[0].reason or "confidence" in reviews[0].reason.lower()


async def test_no_human_claim_in_output(db):
    """AI reply must not claim to be human or deny being bot."""
    dialog, client = await _setup_db(db)
    FORBIDDEN_PHRASES = [
        "я живой человек",
        "общаетесь с живым человеком",
        "я не бот",
        "это не бот",
        "записала голосовое",
    ]
    output = AgentOutput(
        client_reply="Понимаю Ваши сомнения. Мы работаем внутри Монро Арт, могу показать реквизиты.",
        status_before="interested", status_after="interested",
        funnel_stage="objection", confidence_score=0.80,
        need_curator=False, internal_note="distrust objection",
    )
    with patch("app.ai.runner.Runner.run", new_callable=AsyncMock) as m:
        m.return_value = _mock_result(output)
        ai_run = await run_agent_for_dialog(db, dialog.id, client.id, "Вы бот?")

    reply = ai_run.raw_response.get("client_reply", "").lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in reply, f"Forbidden phrase found: '{phrase}'"


async def test_ai_does_not_create_scheduled_tasks(db):
    """Runner must not produce any scheduled/followup/ping artifacts."""
    dialog, client = await _setup_db(db)
    output = AgentOutput(
        client_reply="Хорошо, жду Вашего ответа!",
        status_before="calculated", status_after="calculated",
        funnel_stage="waiting", confidence_score=0.85,
        need_curator=False, internal_note="waiting for client",
    )
    with patch("app.ai.runner.Runner.run", new_callable=AsyncMock) as m:
        m.return_value = _mock_result(output)
        ai_run = await run_agent_for_dialog(db, dialog.id, client.id, "Подумаю")

    raw = str(ai_run.raw_response)
    for forbidden in ["scheduled", "followup", "follow_up", "ping", "reminder", "cron"]:
        assert forbidden not in raw.lower(), f"Scheduled artifact found: '{forbidden}'"


async def test_message_history_persisted(db):
    """Both client message and AI reply must be saved in messages table."""
    dialog, client = await _setup_db(db)
    output = AgentOutput(
        client_reply="Конечно! Подскажите формат?",
        status_before="interested", status_after="interested",
        funnel_stage="format_selection", confidence_score=0.88,
        need_curator=False, internal_note="",
    )
    with patch("app.ai.runner.Runner.run", new_callable=AsyncMock) as m:
        m.return_value = _mock_result(output)
        await run_agent_for_dialog(db, dialog.id, client.id, "Хочу фотокнигу")

    from sqlalchemy import select
    from app.db.models import Message, MessageRole
    result = await db.execute(select(Message).where(Message.dialog_id == dialog.id))
    messages = result.scalars().all()
    roles = [m.role for m in messages]
    assert MessageRole.client in roles
    assert MessageRole.ai in roles
    client_msg = next(m for m in messages if m.role == MessageRole.client)
    assert "фотокнигу" in client_msg.text
    ai_msg = next(m for m in messages if m.role == MessageRole.ai)
    assert "формат" in ai_msg.text.lower()
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests PASSED.

- [ ] **Step 3: Commit**

```bash
git add tests/test_objections.py
git commit -m "test: objection behavior, human-claim guard, no-ping enforcement, history persistence"
```

---

### Task 22: import_dialog_examples command + README

**Files:**
- Create: `app/commands/import_dialog_examples.py`
- Create: `README.md`

- [ ] **Step 1: Create `app/commands/import_dialog_examples.py`**

```python
"""
python -m app.commands.import_dialog_examples --label success --ids "8216574;8216550"
python -m app.commands.import_dialog_examples --label fail --ids "8213682;8213984"
"""
import argparse
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.db.models import DialogExample, DialogExampleLabel


async def import_examples(label: str, ids: list[str]):
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    label_enum = DialogExampleLabel[label]

    async with SessionLocal() as db:
        from sqlalchemy import select
        for crm_id in ids:
            crm_id = crm_id.strip()
            if not crm_id:
                continue
            existing = await db.execute(
                select(DialogExample).where(DialogExample.crm_dialog_id == crm_id)
            )
            if existing.scalar_one_or_none():
                print(f"  skip (exists): {crm_id}")
                continue
            db.add(DialogExample(crm_dialog_id=crm_id, label=label_enum))
            print(f"  imported: {crm_id} ({label})")
        await db.commit()

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, choices=["success", "fail"])
    parser.add_argument("--ids", required=True, help="Semicolon-separated CRM dialog IDs")
    args = parser.parse_args()
    ids = args.ids.split(";")
    asyncio.run(import_examples(args.label, ids))
```

- [ ] **Step 2: Test import command**

```bash
python -m app.commands.import_dialog_examples --label success --ids "8216574;8216550;8216530"
python -m app.commands.import_dialog_examples --label fail --ids "8213682;8213984"
```

Expected:
```
  imported: 8216574 (success)
  imported: 8216550 (success)
  ...
Done.
```

- [ ] **Step 3: Create `README.md`**

```markdown
# Monro AI Layer

AI sales agent for Monroe Art photobooks. One curator controls 300–400 leads/day via AI-assisted messaging.

## Quick start (local)

### Prerequisites

- Python 3.12+, uv, Node 20+, Docker

### 1. Clone + install

```bash
git clone <repo>
cd MonroeAILayer
uv pip install -e ".[dev]"
cd frontend && npm install && cd ..
```

### 2. Create `.env`

```bash
cp .env.example .env
# Edit .env: add OPENAI_API_KEY or ANTHROPIC_API_KEY
```

### 3. Start PostgreSQL

```bash
docker compose up db -d
```

### 4. Apply migrations

```bash
alembic upgrade head
```

### 5. Seed data

```bash
python -m app.commands.seed
```

Creates: admin@monroe.ru / admin123, curator@monroe.ru / curator123, tester@monroe.ru / tester123

### 6. Run backend

```bash
uv run uvicorn app.main:app --reload
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### 7. Run frontend (dev)

```bash
cd frontend && npm run dev
# UI: http://localhost:5173
```

### 8. Build frontend for production

```bash
cd frontend && npm run build
# dist/ is served automatically by FastAPI at http://localhost:8000
```

## Docker Compose (all-in-one)

```bash
cd frontend && npm run build && cd ..
docker compose up --build
# App: http://localhost:8000
```

## Choosing AI provider

In `.env`:

```env
# OpenAI
AI_PROVIDER=openai
MODEL_NAME=gpt-4o

# Anthropic
AI_PROVIDER=anthropic
MODEL_NAME=claude-sonnet-4-6
```

## Testing CRM webhook

```bash
curl -X POST http://localhost:8000/crm/webhook/message \
  -H "Content-Type: application/json" \
  -d '{
    "crm_dialog_id": "test-dialog-001",
    "crm_client_id": "test-client-001",
    "client_name": "Тест Клиент",
    "text": "Здравствуйте, хочу заказать фотокнигу"
  }'
```

## Tester chat

1. Open http://localhost:5173
2. Login as tester@monroe.ru / tester123
3. Write as a client — AI responds as sales agent
4. See cost / confidence / script in right panel

## AI cost tracking

Every AI response stores `cost_amount`, `cost_currency`, `cost_estimated` in `ai_runs` table.
View per-dialog cost in tester chat metadata strip or via `GET /admin/metrics` (admin role).

## Curator review flow

1. AI generates response → if `confidence_score < 0.72` or `need_curator=true` → `curator_review` created
2. Curator opens http://localhost:5173/curator
3. Sees pending reviews with AI draft and handoff reason
4. Clicks Approve / Edit+Send / Reject / Take Over

## Send modes

`AI_SEND_MODE` in `.env`:
- `draft_only` (default) — AI proposes, curator confirms
- `auto_safe` — AI sends automatically if confidence ≥ threshold and no flags
- `manual` — humans write everything

## What is mock / what needs real CRM

Mock (MVP):
- `MockCRMAdapter` in `app/crm/mock.py`
- `send_crm_reply` tool saves draft, does not actually send to VK/CRM
- `fetch_crm_dialog` returns stub data

To connect real CRM: implement `CRMAdapter` ABC in `app/crm/` and set `CRM_ADAPTER=real` in settings.

## Running tests

```bash
pytest tests/ -v
```

Tests use SQLite in-memory + mocked LLM calls. No OpenAI/Anthropic API key required for tests.

## Import dialog examples

```bash
python -m app.commands.import_dialog_examples --label success --ids "8216574;8216550;8216530"
python -m app.commands.import_dialog_examples --label fail --ids "8213682;8213984"
```
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests PASSED.

- [ ] **Step 5: Final commit**

```bash
git add app/commands/import_dialog_examples.py README.md
git commit -m "feat: import_dialog_examples command and README"
```

---

## Self-review against spec

| Spec section | Task(s) covering it |
|---|---|
| §1 Stack | Task 1 |
| §2 Main result — all 12 capabilities | Tasks 11–15 |
| §3 Ethics rules | Task 21 test_no_human_claim; runner enforces; prompts in seed |
| §4 Agent architecture | Tasks 9–11 |
| §5 Tools | Task 9 |
| §6 JSON response format | Task 8 (AgentOutput) |
| §7 Funnel statuses | Task 4 (statuses.py) |
| §8 Price table | Tasks 4, 6 (seed) |
| §9 Scripts | Tasks 5, 6 |
| §10 Objection handling | Task 21; prompts in seed |
| §11 FAQ | Tasks 5, 6 |
| §12 Dialog examples | Task 22 |
| §13 DB schema | Task 2 |
| §14 API endpoints | Tasks 12–15 |
| §15 UI | Tasks 17–20 |
| §16 Cost logging | Tasks 8, 11 |
| §17 Quality rules | Task 21; prompts |
| §18 System prompt | Task 6 (seed) |
| §19 CRM adapter | Task 7 |
| §20 Send modes | Tasks 11, 22 (README) |
| §21 Metrics | Task 15 |
| §22 Tests | Tasks 3–8, 21 |
| §23 Seed data | Task 6 |
| §24 Implementation order | Tasks 1→22 |
| §25 Repository structure | Tasks 1–22 |
| §26 README | Task 22 |
| §27 Done criteria | Tasks 1–22 combined |
