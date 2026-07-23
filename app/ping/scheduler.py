"""Asyncio background ping scheduler.

Discovery and due-send run in two independent loops so a slow due-send pass
(each ping is an LLM + VK round-trip) can never starve discovery of new dialogs.
"""
import asyncio
import logging

from app.config import settings
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
    ]
