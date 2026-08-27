"""Asyncio background ping scheduler.

Discovery and due-send run in two independent loops so a slow due-send pass
(each ping is an LLM + VK round-trip) can never starve discovery of new dialogs.

Здесь же запускается наблюдатель за ответами менеджера в MAX: к пингам он не
относится, но живёт по тому же принципу — фоновый цикл внутри приложения.
"""
import asyncio
import logging

from app.config import settings
from app.max.manager_watch import watch_once
from app.ping.silent_greeting import send_price_to_silent
from app.ping.worker import discover, process_due

logger = logging.getLogger(__name__)


async def _run_loop(name: str, coro, interval: int) -> None:
    logger.info("ping %s loop started | interval=%ds", name, interval)
    while True:
        try:
            await coro()
        except Exception as exc:
            logger.error("ping %s loop error: %s", name, exc, exc_info=True)
        await asyncio.sleep(interval)


def start() -> list[asyncio.Task]:
    return [
        asyncio.create_task(
            _run_loop("due", process_due, settings.PING_INTERVAL_SECONDS)
        ),
        asyncio.create_task(
            _run_loop("discovery", discover, settings.PING_DISCOVERY_INTERVAL_SECONDS)
        ),
        # Молчание после вопроса про надпись закрывается ценой — это не пинг по
        # правилу, а шаг воронки, поэтому отдельным циклом.
        asyncio.create_task(
            _run_loop(
                "silent-greeting", send_price_to_silent,
                settings.PING_DISCOVERY_INTERVAL_SECONDS,
            )
        ),
        # Ответы менеджера в MAX, ушедшие мимо панели: событий о них MAX не
        # присылает, историю диалогов читаем сами (app.max.manager_watch).
        asyncio.create_task(
            _run_loop(
                "max-manager-watch", watch_once,
                settings.MAX_MANAGER_WATCH_INTERVAL_SECONDS,
            )
        ),
    ]
