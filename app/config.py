from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://monroe:monroe@localhost:5432/monroe"
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080

    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    MINIMAX_API_KEY: str = ""
    # Qwen routed through the MuleRouter OpenAI-compatible gateway (not native DashScope).
    # Built into an OpenAIChatCompletionsModel with this base_url/key in providers.py.
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://api.mulerouter.ai/vendors/openai/v1"
    QWEN_MODEL_NAME: str = "qwen-max-latest"
    AI_PROVIDER: str = "openai"
    PING_AI_PROVIDER: str = "openai"
    MODEL_NAME: str = "gpt-4.1"
    ANTHROPIC_MODEL_NAME: str = "claude-sonnet-4-6"
    # Pings are low-stakes (funnel classify + script pick) — run them on a cheaper model
    # than the main sales dialog. Used when PING_AI_PROVIDER=anthropic.
    PING_ANTHROPIC_MODEL_NAME: str = "claude-haiku-4-5"
    MINIMAX_MODEL_NAME: str = "MiniMax-M3"
    # Retry model used when the primary MiniMax model returns an empty/unsalvageable reply.
    MINIMAX_MODEL_NAME_FALLBACK: str = "MiniMax-M2.7"
    # MiniMax exposes an Anthropic-compatible endpoint; we route MiniMax through the
    # anthropic SDK against this base_url so tool calls come back as structured tool_use
    # blocks instead of M3's [TOOL_CALL_BEGIN] text markup (which the OpenAI endpoint leaks).
    MINIMAX_ANTHROPIC_BASE_URL: str = "https://api.minimax.io/anthropic"
    AI_SEND_MODE: str = "draft_only"
    CONFIDENCE_THRESHOLD: float = 0.72

    # Ссылка на оплату. Живой менеджер выставляет счёт руками в платёжной системе,
    # генерации у нас пока нет — и пустое значение здесь означает именно это.
    # Пока ссылки нет, дойдя до оплаты ИИ зовёт куратора вместо того, чтобы слать
    # заглушку: «просто куратора будет звать когда нужно оплачивать» (решение
    # заказчика перед первым тестом на живых клиентах).
    # Появится настоящая ссылка — впиши её сюда, и ИИ снова начнёт отправлять счёт
    # сам, ничего больше менять не нужно.
    PAYMENT_LINK_URL: str = ""

    # Уведомления менеджерам об эскалации (см. app.notify). Пусто — не шлём.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALERT_CHAT_ID: str = ""
    # Адрес панели снаружи: из него собирается ссылка на диалог в уведомлении.
    PANEL_PUBLIC_URL: str = ""

    ALLOWED_ORIGINS: str = "*"

    # Версия VK API для messages.send и прочих вызовов. Токены групп живут в БД
    # (таблица vk_groups), не в env — групп много, их добавляют через админку.
    VK_API_VERSION: str = "5.199"

    # Bot API мессенджера MAX. Токены ботов, как и токены групп ВК, живут в БД
    # и добавляются через админку. Здесь только адрес самого API — он один на
    # всех ботов и меняется разве что при переезде платформы.
    MAX_API_BASE: str = "https://platform-api2.max.ru"

    # Каталог с корневыми сертификатами Минцифры (см. app.ssl_trust). Без них
    # проверка сертификата MAX не проходит и бот молча не отвечает. Путь
    # относительный — считается от корня проекта.
    RU_TRUSTED_CA_DIR: str = "certs"

    # Загруженные из админки файлы лежат на самом сервере (был S3, стало незачем).
    # Путь относительный — считается от корня проекта; в прод-компоуз каталог
    # смонтирован томом, иначе деплой уносил бы картинки вместе с контейнером.
    MEDIA_ROOT: str = "data/media"
    # Домен, по которому файлы доступны снаружи: ссылку читают и модель, и ВК.
    # Пусто — ссылки относительные, годятся только для браузера админки.
    MEDIA_PUBLIC_URL: str = ""
    # Потолок для загрузки из админки: фото с телефона бывает и на 8 МБ.
    MEDIA_MAX_UPLOAD_MB: int = 20

    # Ответы менеджера в MAX, ушедшие мимо панели. О них не приходит вебхука
    # (см. app.max.manager_watch), поэтому историю диалога читаем сами: фоновым
    # проходом и проверкой перед каждой отправкой.
    MAX_MANAGER_WATCH_ENABLED: bool = True
    MAX_MANAGER_WATCH_INTERVAL_SECONDS: int = 60
    # Насколько свежие диалоги проверяет фоновый проход. Переписка старше суток
    # менеджеру уже не принадлежит, но запас берём с избытком.
    MAX_MANAGER_WATCH_WINDOW_HOURS: int = 72

    PING_INTERVAL_SECONDS: int = 60
    PING_ENABLED: bool = True
    # Max due states processed per due-send pass. Bounds pass duration (each state is
    # an LLM + VK round-trip) so a backlog can't make a single pass run unbounded.
    PING_DUE_BATCH_SIZE: int = 50
    # Concurrent states per due-send pass. Each is an independent LLM + VK round-trip
    # in its own DB session; bounded to keep LLM/VK rate limits and DB pool in check.
    PING_DUE_CONCURRENCY: int = 8
    # Discovery runs in its own loop so heavy due-send ticks can't starve it.
    PING_DISCOVERY_INTERVAL_SECONDS: int = 30
    # Max dialogs scanned per discovery pass (oldest-waiting first).
    PING_DISCOVERY_LIMIT: int = 40
    # Ignore dialogs silent longer than this — the moment to ping has passed.
    PING_DISCOVERY_MAX_AGE_HOURS: int = 24

    AI_RUNNER_TIMEOUT: int = 180

    # Estimated tax/VAT applied to AI cost in analytics. 0.20 = +20%. 0 = disabled.
    ESTIMATED_TAX_RATE: float = 0.0

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
