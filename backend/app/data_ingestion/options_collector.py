"""
Background polling service for live option-chain collection.

This collector now has two responsibilities:
- run a once-per-trading-day startup recovery check to bootstrap stale data
- fetch live option-chain updates only while the Indian market is open
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.alerts.alert_engine import run_all_symbols
from app.analytics.dashboard_cache import refresh_dashboard_snapshot_cache
from app.analytics.feature_builder import run_feature_snapshot_cycle
from app.analytics.signal_runner import run_signal_engine_cycle
from app.config import settings
from app.data_ingestion.data_recovery import run_startup_recovery_cycle
from app.data_ingestion.data_source_router import get_data_source
from app.data_ingestion.snapshot_store import persist_chain_snapshots
from app.db.database import AsyncSessionLocal
from app.logging_config import get_logger
from app.services.market_hours import current_trading_date, should_refresh_intraday_caches

logger = get_logger(__name__)


def _is_market_open() -> bool:
    """Return True when the Indian cash market session is open."""
    return should_refresh_intraday_caches()


def _get_sqs_client():
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )


async def _publish_sqs_event(symbol: str, underlying_price: float) -> None:
    if not settings.sqs_queue_url:
        return
    try:
        loop = asyncio.get_event_loop()
        client = _get_sqs_client()
        message = json.dumps(
            {
                "event": "chain_updated",
                "symbol": symbol,
                "underlying_price": underlying_price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        await loop.run_in_executor(
            None,
            lambda: client.send_message(
                QueueUrl=settings.sqs_queue_url,
                MessageBody=message,
            ),
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning("SQS publish failed", symbol=symbol, error=str(exc))


async def _run_post_collection_jobs() -> None:
    try:
        await run_all_symbols()
    except Exception as exc:
        logger.warning("Alert evaluation failed (will retry next cycle)", error=str(exc))

    try:
        await run_signal_engine_cycle()
    except Exception as exc:
        logger.warning("Signal engine failed (will retry next cycle)", error=str(exc))

    try:
        await refresh_dashboard_snapshot_cache()
    except Exception as exc:
        logger.warning("Dashboard snapshot cache refresh failed (will retry next cycle)", error=str(exc))


async def _collect_symbol(symbol: str) -> bool:
    source = get_data_source()
    logger.info("Fetching option chain", symbol=symbol)

    records = await source.fetch_option_chain(symbol)
    if not records:
        logger.warning("Empty chain response", symbol=symbol)
        return False

    underlying = float(records[0].get("underlying_price") or 0.0)

    async with AsyncSessionLocal() as session:
        persisted_at = await persist_chain_snapshots(session, symbol, records)
        if underlying and persisted_at is not None:
            await run_feature_snapshot_cycle(session, symbol, persisted_at, underlying)
        await session.commit()

    logger.info("Persisted snapshots", symbol=symbol, count=len(records))
    await _publish_sqs_event(symbol, underlying)
    return True


async def run_collector() -> None:
    """Run forever, polling at the configured interval."""
    logger.info(
        "Options collector started",
        interval=settings.poll_interval_seconds,
        symbols=settings.supported_symbols,
    )

    last_recovery_date = None

    while True:
        boot_date = current_trading_date()
        recovery_triggered = False

        if boot_date != last_recovery_date:
            try:
                recovery_result = await run_startup_recovery_cycle()
                logger.info("Startup recovery checked", **recovery_result)
                recovery_triggered = recovery_result.get("status") == "completed"
            except Exception as exc:
                logger.warning("Startup recovery check failed", error=str(exc))
            last_recovery_date = boot_date

        live_cycle_had_updates = False
        if _is_market_open():
            try:
                for symbol in settings.supported_symbols:
                    try:
                        live_cycle_had_updates = await _collect_symbol(symbol) or live_cycle_had_updates
                    except Exception as exc:
                        logger.warning(
                            "Collector cycle error (will retry)",
                            symbol=symbol,
                            error=str(exc),
                        )
                    await asyncio.sleep(3)
            except Exception as exc:
                logger.warning("Collector outer error (will retry)", error=str(exc))
        else:
            logger.info(
                "Market closed - skipping live fetch",
                data_source=settings.data_source,
            )

        if recovery_triggered or live_cycle_had_updates:
            await _run_post_collection_jobs()

        await asyncio.sleep(settings.poll_interval_seconds)
