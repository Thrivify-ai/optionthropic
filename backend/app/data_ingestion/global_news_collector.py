"""
Background polling loop for critical global-market alerts.
"""

from __future__ import annotations

import asyncio

from app.alerts.global_news import refresh_global_news_alerts
from app.config import settings
from app.logging_config import get_logger
from app.services.market_hours import global_news_poll_interval_seconds

logger = get_logger(__name__)


async def run_global_news_collector() -> None:
    logger.info("Global news collector started", enabled=settings.global_news_enabled)

    while True:
        try:
            if settings.global_news_enabled:
                await refresh_global_news_alerts()
        except Exception as exc:
            logger.warning("Global news collector cycle failed", error=str(exc))

        await asyncio.sleep(global_news_poll_interval_seconds())
