"""CRUD подключённых ботов MAX (только admin). Токен наружу не отдаётся — маска.

Подключение бота целиком живёт здесь: админ вставляет токен и включает галочку,
а подписку на вебхук (POST /subscriptions) ставим мы. Ходить в кабинет MAX и
прописывать адрес руками не нужно — иначе «включить обработку» означало бы две
операции в двух разных местах, и забытая вторая выглядела бы как «бот не
работает».
"""
import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.config import settings
from app.db.models import Client, User, VkGroup
from app.db.session import get_db
from app.max import client as max_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/max-bots", tags=["max-bots"])

PLATFORM = "max"


def _mask_token(token: str | None) -> str:
    if not token:
        return ""
    return f"…{token[-4:]}" if len(token) > 4 else "…"


def webhook_url(bot_pk: int) -> str:
    """Адрес, который получит события этого бота.

    Собирается из PANEL_PUBLIC_URL: MAX принимает только https, и адрес должен
    быть тем же, по которому панель доступна снаружи.
    """
    base = (settings.PANEL_PUBLIC_URL or "").strip().rstrip("/")
    if not base:
        raise HTTPException(
            status_code=400,
            detail=(
                "Не задан PANEL_PUBLIC_URL — MAX некуда присылать события. "
                "Впишите в .env адрес панели (https://…) и перезапустите сервис."
            ),
        )
    if not base.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail=f"MAX принимает только https-адрес вебхука, а PANEL_PUBLIC_URL = {base}",
        )
    return f"{base}/webhook/max/{bot_pk}"


class MaxBotOut(BaseModel):
    id: int
    bot_id: int
    name: str
    username: str | None
    access_token_mask: str
    webhook_subscribed: bool
    webhook_url: str
    dialog_type_id: int | None
    is_active: bool
    created_at: datetime


class MaxBotCreateRequest(BaseModel):
    name: str
    access_token: str
    dialog_type_id: int | None = None
    is_active: bool = True


class MaxBotUpdateRequest(BaseModel):
    name: str | None = None
    access_token: str | None = None  # пустое/None = не менять
    dialog_type_id: int | None = None
    is_active: bool | None = None


def _to_out(bot: VkGroup) -> MaxBotOut:
    base = (settings.PANEL_PUBLIC_URL or "").strip().rstrip("/")
    return MaxBotOut(
        id=bot.id,
        bot_id=bot.group_id,
        name=bot.name,
        username=bot.username,
        access_token_mask=_mask_token(bot.access_token),
        webhook_subscribed=bool(bot.webhook_subscribed),
        webhook_url=f"{base}/webhook/max/{bot.id}" if base else "",
        dialog_type_id=bot.dialog_type_id,
        is_active=bool(bot.is_active),
        created_at=bot.created_at,
    )


async def _fetch_bot_identity(token: str) -> tuple[int, str | None]:
    """ID и @username бота из GET /me. Заодно проверка, что токен рабочий."""
    try:
        me = await max_api.get_me(token)
    except max_api.MaxApiError as exc:
        raise HTTPException(
            status_code=400, detail=f"MAX не принял токен: {exc.message}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"MAX недоступен: {exc}",
        ) from exc
    bot_id = me.get("user_id")
    if bot_id is None:
        raise HTTPException(status_code=502, detail="MAX не вернул ID бота")
    return int(bot_id), me.get("username")


async def _apply_subscription(bot: VkGroup, enabled: bool) -> None:
    """Включить или выключить подписку бота на вебхук на стороне MAX."""
    url = webhook_url(bot.id)
    try:
        if enabled:
            if not bot.secret_key:
                bot.secret_key = secrets.token_urlsafe(24)
            await max_api.subscribe(bot.access_token, url, bot.secret_key)
            bot.webhook_subscribed = True
            logger.info("MAX: бот %s подписан на вебхук %s", bot.group_id, url)
        else:
            await max_api.unsubscribe(bot.access_token, url)
            bot.webhook_subscribed = False
            logger.info("MAX: бот %s отписан от вебхука", bot.group_id)
    except max_api.MaxApiError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"MAX отказал в настройке вебхука: {exc.message}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MAX недоступен: {exc}") from exc


@router.get("/", response_model=list[MaxBotOut])
async def list_max_bots(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(VkGroup).where(VkGroup.platform == PLATFORM).order_by(VkGroup.id)
    )
    return [_to_out(b) for b in result.scalars().all()]


@router.post("/", response_model=MaxBotOut, status_code=201)
async def create_max_bot(
    body: MaxBotCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    token = (body.access_token or "").strip()
    if not token:
        raise HTTPException(status_code=422, detail="Токен бота обязателен")

    bot_id, username = await _fetch_bot_identity(token)
    existing = await db.scalar(
        select(VkGroup).where(
            VkGroup.platform == PLATFORM, VkGroup.group_id == bot_id,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Этот бот уже подключён — «{existing.name}»",
        )

    bot = VkGroup(
        platform=PLATFORM,
        group_id=bot_id,
        name=body.name.strip() or (username or f"MAX {bot_id}"),
        username=username,
        access_token=token,
        confirmation_code=None,
        secret_key=secrets.token_urlsafe(24),
        dialog_type_id=body.dialog_type_id,
        # Активным бот становится только после успешной подписки ниже: иначе
        # галочка стояла бы, а события не приходили.
        is_active=False,
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)

    if body.is_active:
        await _apply_subscription(bot, True)
        bot.is_active = True
        await db.commit()
        await db.refresh(bot)
    return _to_out(bot)


@router.patch("/{bot_pk}", response_model=MaxBotOut)
async def update_max_bot(
    bot_pk: int,
    body: MaxBotUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    bot = await db.get(VkGroup, bot_pk)
    if not bot or bot.platform != PLATFORM:
        raise HTTPException(status_code=404, detail="MAX bot not found")

    updates = body.model_dump(exclude_unset=True)
    # Пустой токен в PATCH означает «оставить текущий» (в UI он показан маской).
    new_token = (updates.pop("access_token", None) or "").strip()
    was_active = bool(bot.is_active)
    want_active = updates.pop("is_active", was_active)

    if new_token and new_token != bot.access_token:
        bot_id, username = await _fetch_bot_identity(new_token)
        clash = await db.scalar(
            select(VkGroup).where(
                VkGroup.platform == PLATFORM,
                VkGroup.group_id == bot_id,
                VkGroup.id != bot.id,
            )
        )
        if clash:
            raise HTTPException(
                status_code=409, detail=f"Этот бот уже подключён — «{clash.name}»",
            )
        # Старая подписка висит на старом токене: снимаем её, пока он ещё у нас.
        if bot.webhook_subscribed:
            try:
                await max_api.unsubscribe(bot.access_token, webhook_url(bot.id))
            except Exception as exc:
                logger.warning("MAX: не удалось снять старую подписку: %s", exc)
            bot.webhook_subscribed = False
        bot.access_token = new_token
        bot.group_id = bot_id
        bot.username = username

    for k, v in updates.items():
        setattr(bot, k, v)

    if want_active and not (was_active and bot.webhook_subscribed):
        await _apply_subscription(bot, True)
    elif not want_active and bot.webhook_subscribed:
        await _apply_subscription(bot, False)
    bot.is_active = bool(want_active)

    await db.commit()
    await db.refresh(bot)
    return _to_out(bot)


@router.post("/{bot_pk}/check", response_model=MaxBotOut)
async def check_max_bot(
    bot_pk: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """Спросить у MAX, что он о боте думает: жив ли токен и стоит ли подписка.

    Подписку могли снять с той стороны (сменили токен, пересоздали бота), и
    тогда бот молчит, а в панели он «активен». Кнопка приводит панель в
    соответствие с тем, что на самом деле.
    """
    bot = await db.get(VkGroup, bot_pk)
    if not bot or bot.platform != PLATFORM:
        raise HTTPException(status_code=404, detail="MAX bot not found")

    bot_id, username = await _fetch_bot_identity(bot.access_token)
    bot.group_id = bot_id
    bot.username = username
    try:
        subs = await max_api.list_subscriptions(bot.access_token)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MAX недоступен: {exc}") from exc

    ours = webhook_url(bot.id)
    bot.webhook_subscribed = any((s.get("url") or "").rstrip("/") == ours for s in subs)
    await db.commit()
    await db.refresh(bot)
    return _to_out(bot)


@router.delete("/{bot_pk}", status_code=204)
async def delete_max_bot(
    bot_pk: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    bot = await db.get(VkGroup, bot_pk)
    if not bot or bot.platform != PLATFORM:
        raise HTTPException(status_code=404, detail="MAX bot not found")

    # Клиенты ссылаются на канал внешним ключом — удаление бота, через которого
    # кто-то писал, унесло бы с собой всю переписку (или упало бы на FK, как это
    # было с группами ВК). Выключение решает ту же задачу без потерь.
    clients = await db.scalar(
        select(func.count(Client.id)).where(Client.vk_group_id == bot.id)
    )
    if clients:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Через этого бота писали {clients} клиент(ов), их переписка ссылается "
                f"на него. Удалить нельзя — снимите галочку «Активен», тогда ИИ "
                f"перестанет отвечать, а история останется."
            ),
        )

    if bot.webhook_subscribed:
        try:
            await max_api.unsubscribe(bot.access_token, webhook_url(bot.id))
        except Exception as exc:
            logger.warning("MAX: не удалось снять подписку при удалении: %s", exc)

    await db.delete(bot)
    await db.commit()
