import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.logging_context import PerTypeFileHandler
from app.storage.local import media_root

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s — %(message)s"
_LOG_DATE = "%Y-%m-%d %H:%M:%S"

_logs_dir = Path(__file__).parent.parent / "logs"
_logs_dir.mkdir(exist_ok=True)

_file_handler = PerTypeFileHandler(
    filename="app.log",
    logs_dir=_logs_dir,
    when="midnight",
    interval=1,
    backupCount=6,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE))

_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE))

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _stream_handler])

_ping_file_handler = PerTypeFileHandler(
    filename="ping.log",
    logs_dir=_logs_dir,
    when="midnight",
    interval=1,
    backupCount=2,
    encoding="utf-8",
)
_ping_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE))
_ping_logger = logging.getLogger("app.ping")
_ping_logger.addHandler(_ping_file_handler)
_ping_logger.propagate = False

_vk_webhook_logger = logging.getLogger("app.vk.webhook")
_vk_webhook_logger.addHandler(_file_handler)
_vk_webhook_logger.propagate = False

_vk_sender_logger = logging.getLogger("app.vk.sender")
_vk_sender_logger.addHandler(_ping_file_handler)
_vk_sender_logger.propagate = False

for _noisy in ("openai", "anthropic", "httpx", "httpcore", "openai._base_client", "LiteLLM"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.ping.scheduler import start as start_ping
    tasks = start_ping()
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Hemilton AI Layer", version="0.1.0", lifespan=lifespan)

allowed_origins = (
    ["*"] if settings.ALLOWED_ORIGINS == "*"
    else [o.strip() for o in settings.ALLOWED_ORIGINS.split(",")]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=settings.ALLOWED_ORIGINS != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.auth.router import router as auth_router
from app.api.dialogs import router as dialogs_router
from app.api.chat import router as chat_router
from app.api.admin import router as admin_router
from app.api.scripts import router as scripts_router
from app.api.dialog_types import router as dialog_types_router
from app.api.dialog_statuses import router as dialog_statuses_router
from app.api.ping_rules import router as ping_rules_router
from app.api.vk import router as vk_webhook_router
from app.api.vk_groups import router as vk_groups_router
from app.api.feedback import router as feedback_router
from app.api.ref_tags import router as ref_tags_router

app.include_router(auth_router, prefix="/api/auth")
app.include_router(dialogs_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(scripts_router, prefix="/api")
app.include_router(dialog_types_router, prefix="/api")
app.include_router(dialog_statuses_router, prefix="/api")
app.include_router(ping_rules_router, prefix="/api")
app.include_router(vk_groups_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(ref_tags_router, prefix="/api")
# Вебхук ВК без /api-префикса: адрес в настройках Callback API — /webhook/vk.
app.include_router(vk_webhook_router)

# Файлы из админки: каталог создаём сами и монтируем ДО SPA-роута ниже, иначе
# «/media/...» уехал бы в index.html вместе со всеми неизвестными адресами.
_media_root = media_root()
_media_root.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=_media_root), name="media")

frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        ico = frontend_dist / "favicon.ico"
        return FileResponse(ico) if ico.exists() else FileResponse(frontend_dist / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # index.html не кэшируем: имена бандлов в нём хэшированные, и стоит
        # браузеру придержать старый index — админка после деплоя продолжает
        # работать на прошлой сборке. Правку реф-меток так и не увидели, пока
        # не обновили страницу руками. Сами бандлы под хэшем — наоборот,
        # неизменны, их можно держать сколько угодно.
        return FileResponse(
            frontend_dist / "index.html",
            headers={"Cache-Control": "no-store, must-revalidate"},
        )
