# VK AI Sales Layer

ИИ-агент продаж поверх личных сообщений (компания по продаже одежды). Работает
в двух мессенджерах: сообщества **ВКонтакте** (Callback API + `messages.send`) и
боты **MAX** (Bot API). Принимает входящие, генерирует структурированные ответы
(OpenAI/Anthropic/Qwen/MiniMax), отправляет их клиенту, уводит низкоуверенные
ответы на ревью куратора; включает пинг-подсистему follow-up сообщений, тестовый
чат и админку. Логика продаж у платформ общая — различается только транспорт.
Вся история диалогов хранится в собственной БД — внешней CRM нет.

## Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy async, PostgreSQL (asyncpg), Alembic
- **AI**: openai-agents SDK + LiteLLM (OpenAI / Anthropic / Qwen / MiniMax)
- **Frontend**: Vue 3, Pinia, Vue Router 4, TailwindCSS, Vite
- **Auth**: JWT (python-jose), bcrypt

## Quick start

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, OPENAI_API_KEY (or ANTHROPIC_API_KEY)
# Токены групп ВК в env НЕ хранятся — они добавляются через админку (см. ниже).
```

### 2. Install backend dependencies

```bash
pip install uv
uv pip install -e ".[dev]"
```

### 3. Run migrations

```bash
alembic upgrade head
```

### 4. Seed initial data

```bash
python -m app.commands.seed
# Создаёт: admin@hemilton.ai / admin1234, дефолтное направление, базовые статусы
```

### 5. Start backend

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Start frontend (development)

```bash
cd frontend
npm install
npm run dev
# Opens on http://localhost:5173
```

### 7. Build frontend for production

```bash
cd frontend
npm run build
# Output: frontend/dist/ (served by FastAPI at /)
```

## Подключение группы ВК

Система мультигрупповая: каждое сообщество подключается отдельно через админку
(AdminPage → вкладка «Группы ВК»), у каждой группы может быть своё направление
(dialog type) со своими промтами и скриптами.

### 1. Получить ключ доступа сообщества

В сообществе ВК: **Управление → Работа с API → Ключи доступа → Создать ключ**.
Обязательные права: **«Сообщения сообщества»** (messages). Скопируйте токен —
он вставляется в поле «Токен доступа» при добавлении группы в админке.

### 2. Включить Callback API

**Управление → Работа с API → Callback API**:

- **Версия API**: 5.199 (или значение `VK_API_VERSION` из .env).
- **Адрес**: `https://<ваш-домен>/webhook/vk` — один адрес на все группы,
  система различает их по `group_id` события.
- **Строка, которую должен вернуть сервер** — ВК покажет её сам; вставьте это
  значение в поле «Код подтверждения» группы в админке ДО нажатия «Подтвердить».
- **Секретный ключ** — придумайте строку, впишите её и в настройках ВК, и в поле
  «Секретный ключ» группы в админке. События с неверным секретом отбрасываются (403).

Типы событий: включите **«Входящее сообщение»** (message_new) и
**«Исходящее сообщение»** (message_reply — по нему система понимает, что живой
оператор вмешался в диалог, и ставит ИИ на паузу).

### 3. Добавить группу в админке

AdminPage → «Группы ВК» → «Добавить»: числовой ID сообщества, название, токен,
код подтверждения, секрет, направление. После сохранения нажмите «Подтвердить»
в настройках Callback API ВК — сервер вернёт код подтверждения.

### Как это работает

- `message_new` → сообщение сохраняется, запускается ИИ; ответ уходит клиенту в ЛС
  (или остаётся черновиком в очереди куратора при низком confidence / need_curator).
- `message_reply` от живого оператора (отправка из интерфейса ВК)
  → сообщение сохраняется как «оператор», диалогу ставится флаг **«ИИ на паузе»**;
  снять паузу может куратор в карточке диалога.
- Ошибки ВК 900/901/902 (клиент запретил сообщения сообщества) — диалог помечается
  заблокированным, отправки не ретраятся.
- Тексты длиннее 4096 символов автоматически режутся на несколько сообщений.

## Подключение бота MAX

Мессенджер MAX подключается целиком из админки: **AdminPage → вкладка «Боты
MAX» → «Добавить бота»**. Нужны только название, токен и направление; ID и
`@username` бота подтягиваются из MAX по токену, адрес вебхука прописывается
там же автоматически.

### 1. Получить токен бота

В MAX напишите **@MasterBot**, создайте бота и скопируйте выданный токен.

### 2. Добавить бота в админке

Вставьте токен, выберите направление (dialog type — свои промты и скрипты) и
оставьте галочку **«Активен — включить обработку сообщений»**. При сохранении
система:

- зовёт `GET /me` — проверяет токен и забирает ID и `@username` бота;
- генерирует секрет вебхука и ставит подписку `POST /subscriptions` на адрес
  `https://<домен>/webhook/max/<id бота в системе>`.

Снятая галочка снимает подписку — события перестают приходить, история
остаётся. Кнопка **«Проверить»** в строке бота спрашивает MAX, жив ли токен и
стоит ли подписка (её могли снять с той стороны).

Для автоподписки в `.env` должен быть задан `PANEL_PUBLIC_URL` с **https** —
других адресов MAX не принимает.

### Сертификаты Минцифры

MAX работает по сертификатам «Russian Trusted CA», которых нет в общемировых
хранилищах доверенных корней. Они лежат в каталоге [`certs/`](certs/) и
ставятся при сборке образа — и в системное хранилище, и в связку `certifi` (по
ней проверяет сертификаты httpx). Без них любой запрос к MAX падает с
`CERTIFICATE_VERIFY_FAILED`, и бот молча перестаёт отвечать. Подробности и
порядок обновления — в [certs/README.md](certs/README.md).

### Как это работает

- **Старт диалога.** В ВК первым всегда пишет клиент, а приветствие по кнопке
  «Начать» шлёт само сообщество. В MAX здоровается бот: на `bot_started` и/или
  сообщение `/start` (что именно пришлёт MAX, зависит от того, как открыли
  бота) уходит тот же приветственный скрипт, что и в ВК. Обработчик
  идемпотентный — поздороваться он даст ровно один раз. Текст после команды
  (`/start sweetgold`) и `payload` диплинка становятся маркетинговой меткой
  клиента, как `ref` рекламной ссылки ВК. Сама команда в переписку не
  записывается: клиент её не писал.
- `message_created` → сообщение сохраняется и идёт тем же путём, что и
  сообщение из ВК: дедуп по `mid`, пауза «клиент дописывает», прогон модели,
  отправка ответа. Скрипты, пинги, статусы и очередь куратора — общие.
- `bot_stopped` / `dialog_removed` → диалог помечается заблокированным,
  отправки не ретраятся.
- Голосовые: если MAX прислал расшифровку — берём её, свой Whisper не зовём.
- Картинки уходят вложением по внешней ссылке — перезаливать их, как в ВК, не
  нужно. Тексты длиннее 4000 символов режутся на части.

Боты MAX хранятся в той же таблице `vk_groups`, что и сообщества ВК, — их
различает колонка `platform` (см. миграцию 052). Благодаря этому вся привязка
клиентов, пингов и панели работает для обеих платформ одинаково.

## Docker (production)

```bash
# Set DATABASE_URL in .env to point to external PostgreSQL host
docker compose build
docker compose up -d
# App: http://localhost:8000
```

## API overview

| Prefix | Description |
|--------|-------------|
| `POST /api/auth/login` | Get JWT token |
| `POST /webhook/vk` | VK Callback API (confirmation / message_new / message_reply) |
| `GET/POST /api/vk-groups/` | Управление подключёнными группами ВК (admin) |
| `POST /webhook/max/{id}` | MAX Bot API (message_created / bot_started / bot_stopped) |
| `GET/POST /api/max-bots/` | Управление подключёнными ботами MAX (admin) |
| `GET /api/dialogs/` | List dialogs (admin/curator) |
| `POST /api/dialogs/{id}/ai-pause` | Пауза/возобновление ИИ в диалоге |
| `POST /api/chat/start` | Start test dialog |
| `POST /api/chat/{id}/message` | Send message in test chat |
| `GET /api/scripts/` | Скрипты продаж (условие + готовый текст фразы) |
| `GET /api/ping-rules/` | Пинг-правила (шаги follow-up воронок) |
| `GET /api/admin/metrics` | AI usage + cost metrics |
| `GET /api/admin/users` | User management |

Full OpenAPI docs: `http://localhost:8000/docs`

## AI configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `AI_PROVIDER` | `openai` | `openai` / `anthropic` / `qwen` / `minimax` |
| `MODEL_NAME` | `gpt-4o` | Model identifier |
| `CONFIDENCE_THRESHOLD` | `0.72` | Below this → curator review triggered |
| `VK_API_VERSION` | `5.199` | Версия VK API для messages.send |
| `MAX_API_BASE` | `https://platform-api2.max.ru` | Адрес Bot API мессенджера MAX |
| `RU_TRUSTED_CA_DIR` | `certs` | Каталог с корневыми сертификатами Минцифры (нужны для MAX) |

Скрипты и пинг-фразы хранят готовый текст прямо в БД и поддерживают spintax:
`{вариант1|вариант2|вариант3}` — при отправке выбирается случайный вариант,
чтобы сообщения не выглядели шаблонными.

## User roles

| Role | Access |
|------|--------|
| `admin` | Everything |
| `curator` | Review queue, dialogs, test chat |

## Commands

```bash
# Seed database with initial data (admin, направление, базовые статусы)
python -m app.commands.seed
```

## Running tests

```bash
pytest tests/ -v
```

Tests use SQLite in-memory — no PostgreSQL needed for testing.
