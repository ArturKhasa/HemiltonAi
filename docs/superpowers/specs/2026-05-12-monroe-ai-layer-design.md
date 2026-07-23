# Monro AI Layer — MVP Design Spec
**Date:** 2026-05-12  
**Status:** Approved

---

## Context

AI sales agent layer for Monroe Art (INN 1655461269). Company sells personalized gifts; MVP covers **photobooks only**. Replaces manual VK/social sales chat. One curator controls 300–400 leads/day vs current 70/manager. AI replies only on incoming message — no auto-pings or scheduled follow-ups.

---

## Section 1: Project Structure & Stack

```
MonroeAILayer/
├── app/
│   ├── main.py                  # FastAPI app factory
│   ├── config.py                # Pydantic Settings from .env
│   ├── db/
│   │   ├── session.py           # async engine + get_db()
│   │   ├── models.py            # all SQLAlchemy models
│   │   └── migrations/          # Alembic env + versions/
│   ├── auth/
│   │   ├── router.py            # /auth/register, /login, /me
│   │   ├── service.py
│   │   └── dependencies.py      # get_current_user, require_role
│   ├── crm/
│   │   ├── base.py              # CRMAdapter ABC
│   │   └── mock.py              # MockCRMAdapter
│   ├── ai/
│   │   ├── agents.py            # SalesAgent + ObjectionAgent
│   │   ├── tools.py             # all @tool functions
│   │   ├── providers.py         # LiteLLMModelProvider
│   │   ├── runner.py            # AgentRunner: invoke + persist
│   │   ├── cost.py              # token → cost calculation
│   │   ├── schemas.py           # AgentOutput Pydantic model
│   │   └── prompts.py           # system prompt loader from DB
│   ├── sales/
│   │   ├── statuses.py          # FunnelStatus enum + transitions
│   │   ├── pricing.py           # calculate_price()
│   │   ├── scripts.py           # get_relevant_script()
│   │   └── faq.py               # get_faq_answer()
│   ├── curator/
│   │   ├── router.py            # /curator/reviews/*
│   │   └── service.py
│   ├── api/
│   │   ├── crm_webhook.py       # /crm/webhook/message
│   │   ├── dialogs.py           # /dialogs/*
│   │   ├── ai.py                # /ai/*
│   │   └── admin.py             # /admin/*
│   └── commands/
│       ├── seed.py
│       └── import_dialog_examples.py
├── frontend/                    # Vue 3 + Vite
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Login.vue
│   │   │   ├── TesterChat.vue
│   │   │   ├── CuratorDashboard.vue
│   │   │   ├── CuratorReview.vue
│   │   │   └── AdminSettings.vue
│   │   ├── stores/              # Pinia
│   │   └── api/                 # axios client
│   └── vite.config.ts
├── tests/
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
├── .env.example
└── README.md
```

**Stack:**
- Python 3.12, FastAPI 0.115, SQLAlchemy 2.x async, Alembic, Pydantic v2
- `openai-agents` SDK + `litellm` for provider routing (OpenAI + Anthropic)
- Vue 3 + Vite + Pinia + Axios + Vue Router
- PostgreSQL 16
- `passlib[bcrypt]` + `python-jose` for JWT auth
- `pytest` + `pytest-asyncio` + `httpx` for tests
- `uv` for dependency management

---

## Section 2: Database Schema

### users
`id, email, password_hash, role(admin|curator|tester), created_at, updated_at`

### clients
`id, crm_client_id, name, source, created_at, updated_at`

### dialogs
`id, crm_dialog_id, client_id→clients, current_status, assigned_curator_id→users, is_test, created_at, updated_at, last_message_at`

### messages
`id, dialog_id→dialogs, role(client|ai|curator|system), text, external_message_id, created_at, metadata jsonb`

### status_history
`id, dialog_id, old_status, new_status, reason, changed_by→users, created_at`

### ai_runs
`id, dialog_id, input_message_id, output_message_id, provider, model, prompt_version, input_tokens, output_tokens, total_tokens, cost_amount, cost_currency, cost_estimated bool, latency_ms, confidence_score, need_curator, curator_reason, selected_script, status_before, status_after, raw_response jsonb, created_at`

### model_pricing
`id, provider, model, input_price_per_1m, output_price_per_1m, currency, valid_from, valid_to, is_active`

### price_ladder
`id, product_type, size, spreads_count, regular_price, minimum_price, currency, is_active`

### scripts
`id, name, category, stage, objection_type, body, is_active, created_at, updated_at`

### faq
`id, key, question, answer, is_active, created_at, updated_at`

### curator_reviews
`id, dialog_id, ai_run_id, status(pending|approved|edited|rejected|takeover), ai_draft, final_text, reason, curator_id→users, created_at, resolved_at`

### prompt_versions
`id, name, version, content, is_active, created_at`

### dialog_examples
`id, crm_dialog_id, label(success|fail), imported_at, analyzed_at, notes, conversion_stage, failure_reason, success_pattern`

**Indexes:** `dialogs(current_status)`, `dialogs(assigned_curator_id)`, `messages(dialog_id)`, `ai_runs(dialog_id)`, `curator_reviews(status)`

---

## Section 3: AI Agent Layer

### Agents

**SalesAgent** — main orchestrator. Handles full funnel from greeting to pre-payment.  
**ObjectionAgent** — activated via openai-agents handoff when SalesAgent detects objection type.

Both agents return structured `AgentOutput`:

```python
class AgentOutput(BaseModel):
    client_reply: str
    status_before: str
    status_after: str
    funnel_stage: str
    objection_type: str | None
    selected_script: str | None
    price_offer: float | None
    need_curator: bool
    curator_reason: str | None
    confidence_score: float   # 0.0–1.0, threshold=0.72
    internal_note: str
```

### Tools (registered on SalesAgent)

| Tool | Purpose |
|------|---------|
| `get_client_context(client_id, dialog_id)` | Client + status + history + prior calculations |
| `get_price_ladder()` | Full price table from DB |
| `calculate_photobook_price(size, spreads_count, price_type)` | Single price lookup |
| `get_relevant_script(stage, objection_type)` | Script body for current situation |
| `get_faq_answer(question_type)` | Approved FAQ answer |
| `update_client_status(client_id, dialog_id, new_status, reason)` | Status transition + history |
| `request_curator_review(client_id, dialog_id, reason, ai_draft)` | Creates curator_review |
| `fetch_crm_dialog(dialog_id)` | CRM stub |
| `send_crm_reply(dialog_id, text)` | CRM stub (saves as draft in MVP) |

### Provider abstraction

```python
class LiteLLMModelProvider:
    def get_model(self, model_id: str) -> Model:
        # "gpt-4o" → OpenAI direct
        # "anthropic/claude-sonnet-4-6" → LiteLLM proxy
        return LiteLLMModel(model=model_id)
```

Configured via `AI_PROVIDER` + `MODEL_NAME` in `.env`. Switchable per-environment or per-dialog (admin UI).

### Runner flow

1. Load dialog history + client context from DB
2. Build message list
3. `result = await Runner.run(SalesAgent, messages)`
4. Parse `AgentOutput`
5. Persist `ai_run` row (tokens + cost)
6. If `need_curator=True` or `confidence_score < 0.72` → create `curator_review(pending)`
7. If `AI_SEND_MODE=auto_safe` and safe → call `send_crm_reply`; else → save draft

### Cost calculation

```python
def calculate_cost(usage, pricing) -> Decimal:
    input_cost  = Decimal(usage.input_tokens)  / 1_000_000 * pricing.input_price_per_1m
    output_cost = Decimal(usage.output_tokens) / 1_000_000 * pricing.output_price_per_1m
    return input_cost + output_cost
```

If usage unavailable: estimate via `tiktoken`, set `cost_estimated=True`.

---

## Section 4: API & Data Flow

### Endpoints

**Auth:**
```
POST /auth/register
POST /auth/login        → {access_token, token_type}
GET  /auth/me
```

**CRM integration:**
```
POST /crm/webhook/message         → upsert client/dialog/message → run agent
GET  /crm/dialogs/{dialog_id}
POST /crm/dialogs/{dialog_id}/reply
```

**AI:**
```
POST /ai/test-chat                → tester triggers agent on is_test dialog
POST /ai/generate-reply           → manual trigger (curator/admin)
GET  /ai/runs/{run_id}
```

**Dialogs:**
```
GET  /dialogs
GET  /dialogs/{id}
GET  /dialogs/{id}/messages
```

**Curator:**
```
GET  /curator/reviews
GET  /curator/reviews/{id}
POST /curator/reviews/{id}/approve
POST /curator/reviews/{id}/edit
POST /curator/reviews/{id}/reject
POST /curator/reviews/{id}/takeover
```

**Admin (CRUD):**
```
/admin/scripts, /admin/faq, /admin/price-ladder, /admin/model-pricing, /admin/metrics
```

**WebSocket:**
```
GET  /ws/chat/{dialog_id}         → streams AI response for tester chat
```

### Happy path data flow

```
CRM → POST /crm/webhook/message
      ↓
  upsert client/dialog/message
      ↓
  AgentRunner.run()
      ↓
  SalesAgent → tools → AgentOutput
      ↓
  persist ai_run + output message
      ↓
  confidence >= 0.72 && !need_curator && AI_SEND_MODE=auto_safe?
      ├─ yes → send_crm_reply() → update dialog status
      └─ no  → create curator_review(pending)
```

---

## Section 5: Vue Frontend

**Build:** Vite proxy `/api → :8000` in dev. FastAPI serves `frontend/dist/` as `StaticFiles` in prod.

### Pages

| Page | Route | Key features |
|------|-------|-------------|
| Login/Register | `/login`, `/register` | JWT stored in localStorage |
| TesterChat | `/tester/chat/:dialogId` | Message history, metadata strip (status/model/cost/confidence/script), new dialog button |
| CuratorDashboard | `/curator` | Table with needs_attention badge, filter tabs |
| CuratorReview | `/curator/review/:reviewId` | History + editable draft + approve/edit/reject/takeover buttons |
| AdminSettings | `/admin` | Tabs: Prices, Scripts, FAQ, Models, Metrics |

**Metadata strip in TesterChat** (right panel per AI response):
- Current funnel status
- Model + provider
- Cost: `$0.0023`
- Confidence: `0.86`
- Selected script: `"перед форматом 2"`
- Need curator: `No`

**Pinia stores:** `authStore`, `chatStore`, `curatorStore`, `adminStore`

**Styling:** Tailwind CSS. No charts for MVP — stat cards and tables only.

---

## Section 6: Testing & Deployment

### Tests

```
tests/
  conftest.py          # async SQLite in-memory, test client, fixtures, mock Runner.run
  test_pricing.py      # price table correctness
  test_objections.py   # дорого+бюджет→asks photo; подумаю→asks why; недоверие→no "живой человек"
  test_agent.py        # low confidence→curator_review; cost saved; no ping tasks created
  test_messages.py     # history persistence
  test_crm_webhook.py  # POST /crm/webhook → dialog upsert + ai_run
  test_chat.py         # POST /ai/test-chat → 200 + AgentOutput shape
```

All LLM calls mocked via `unittest.mock.patch` on `Runner.run`.

### Docker Compose

```yaml
services:
  db:
    image: postgres:16
    environment: [POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]
    volumes: [postgres_data:/var/lib/postgresql/data]
  app:
    build: .
    depends_on: [db]
    ports: ["8000:8000"]
    env_file: .env
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Dockerfile:** python:3.12-slim, installs deps, runs `alembic upgrade head` as startup step.

### Local dev

```bash
docker compose up db -d
alembic upgrade head
python -m app.commands.seed
uv run uvicorn app.main:app --reload   # backend :8000
cd frontend && npm run dev              # frontend :5173 (proxied)
```

### .env.example

```
DATABASE_URL=postgresql+asyncpg://monroe:monroe@localhost:5432/monroe
SECRET_KEY=change-me
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
AI_PROVIDER=openai
MODEL_NAME=gpt-4o
AI_SEND_MODE=draft_only
CONFIDENCE_THRESHOLD=0.72
```

---

## Funnel Statuses

| Status | Description |
|--------|-------------|
| `interested` | Greeting, format selection, calculation |
| `calculated` | Price sent, not hot yet |
| `hot` | Client said yes, sending photos |
| `waiting_prepayment` | Payment link sent |
| `order_created` | First prepayment received |
| `needs_curator` | Handed off to curator |
| `lost` | Client gone |
| `no_response` | No reply |
| `spam` | Spam |
| `test` | Test dialog |

---

## Send Modes

| Mode | Behavior |
|------|---------|
| `draft_only` | AI proposes, curator confirms (MVP default) |
| `auto_safe` | AI sends if confidence ≥ threshold and no risk flags |
| `manual` | Human writes everything |

---

## Curator Handoff Triggers

- `confidence_score < 0.72`
- Client is angry or accuses of deception
- Client requests legal guarantees, contract, refund, complaint
- Non-standard order
- Client requests heavy discount
- Payment issue
- AI cannot determine next step
- Client repeated unanswered question 2+ times
- Ambiguous file/photo/personal data received
- Reputational risk detected

---

## Ethics Rules (enforced in system prompt)

AI must never:
- Claim to be a human
- Claim to not be a bot
- Reveal internal script names to client
- Show confidence_score to client
- Show internal reasoning to client

AI must use honest alternatives:
- "Я передам вопрос куратору, если потребуется."
- "Мы компания Монро Бук, работаем внутри Монро Арт."
- "Могу показать реквизиты, отзывы и примеры работ."
