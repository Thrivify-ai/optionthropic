from __future__ import annotations

import asyncio

from app.analytics.quick_signal_engine import run_quick_signal_engine
from app.analytics.quick_signal_observer import capture_quick_quant_observation
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.logging_config import get_logger
from app.services.market_hours import should_refresh_intraday_caches

logger = get_logger(__name__)


async def _run_symbol(symbol: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            payload = await run_quick_signal_engine(session, symbol)
            await capture_quick_quant_observation(session, symbol=symbol, payload=payload)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def run_quick_signal_collector() -> None:
    poll_seconds = max(10, int(settings.quick_signal_poll_seconds))
    logger.info(
        "Quick signal collector started",
        interval=poll_seconds,
        symbols=settings.supported_symbols,
    )

    was_open = None
    while True:
        market_open = should_refresh_intraday_caches()
        if not market_open:
            if was_open is not False:
                logger.info("Quick signal collector paused", reason="market_closed")
            was_open = False
            await asyncio.sleep(max(30, poll_seconds))
            continue

        if was_open is not True:
            logger.info("Quick signal collector active")
        was_open = True

        for symbol in settings.supported_symbols:
            try:
                await _run_symbol(symbol)
            except Exception as exc:
                logger.warning("Quick signal collector cycle failed", symbol=symbol, error=str(exc))
            await asyncio.sleep(1)

        await asyncio.sleep(poll_seconds)
