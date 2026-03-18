"""
Background polling service — runs every POLL_INTERVAL_SECONDS seconds.
Fetches full option chain for each supported symbol, persists raw snapshots
to RDS, and publishes a lightweight update event to SQS.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, time as dtime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.alert_engine import run_all_symbols
from app.analytics.signal_runner import run_signal_engine_cycle
from app.config import settings
from app.data_ingestion.data_source_router import get_data_source
from app.db.database import AsyncSessionLocal
from app.logging_config import get_logger
from app.models.chain_snapshot import ChainSnapshot
from app.models.options_snapshot import OptionsSnapshot

logger = get_logger(__name__)

# IST = UTC+5:30
_IST_OFFSET = timedelta(hours=5, minutes=30)
_MARKET_OPEN  = dtime(9, 0)
_MARKET_CLOSE = dtime(15, 30)


def _is_market_open() -> bool:
    """Return True if current IST time is within 9:00–15:30."""
    now_ist = (datetime.now(timezone.utc) + _IST_OFFSET).time()
    return _MARKET_OPEN <= now_ist <= _MARKET_CLOSE


# ─── SQS publisher ─────────────────────────────────────────────────────────────


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
                QueueUrl=settings.sqs_queue_url, MessageBody=message
            ),
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning("SQS publish failed", symbol=symbol, error=str(exc))


# ─── Persistence helpers ────────────────────────────────────────────────────────


async def _persist_snapshots(
    session: AsyncSession, symbol: str, records: list[dict]
) -> None:
    now = datetime.now(timezone.utc)
    snapshots = []
    chain_map: dict[tuple, dict] = {}

    for r in records:
        snapshots.append(
            OptionsSnapshot(
                symbol=r["symbol"],
                strike=r["strike"],
                expiry=r["expiry"],
                option_type=r["option_type"],
                oi=r["oi"],
                volume=r["volume"],
                last_price=r["last_price"],
                underlying_price=r["underlying_price"],
                timestamp=now,
            )
        )

        key = (r["strike"], r["expiry"])
        if key not in chain_map:
            chain_map[key] = {
                "symbol": symbol,
                "strike": r["strike"],
                "expiry": r["expiry"],
                "call_oi": 0,
                "put_oi": 0,
                "call_volume": 0,
                "put_volume": 0,
                "underlying_price": r["underlying_price"],
                "timestamp": now,
            }
        if r["option_type"] == "CE":
            chain_map[key]["call_oi"] += r["oi"]
            chain_map[key]["call_volume"] += r["volume"]
        else:
            chain_map[key]["put_oi"] += r["oi"]
            chain_map[key]["put_volume"] += r["volume"]

    session.add_all(snapshots)
    for data in chain_map.values():
        session.add(ChainSnapshot(**data))

    await session.flush()


# ─── Poll loop ─────────────────────────────────────────────────────────────────


async def _collect_symbol(symbol: str) -> None:
    source = get_data_source()
    logger.info("Fetching option chain", symbol=symbol)

    records = await source.fetch_option_chain(symbol)
    if not records:
        logger.warning("Empty chain response", symbol=symbol)
        return

    underlying = records[0]["underlying_price"] if records else 0.0

    async with AsyncSessionLocal() as session:
        await _persist_snapshots(session, symbol, records)
        await session.commit()

    logger.info("Persisted snapshots", symbol=symbol, count=len(records))
    await _publish_sqs_event(symbol, underlying)


async def run_collector() -> None:
    """Entry point — runs forever, polling every POLL_INTERVAL_SECONDS.
    Symbols are collected sequentially with a 3s gap to avoid Zerodha rate limits.
    Never raises; failures are logged and retried next cycle."""
    logger.info(
        "Options collector started",
        interval=settings.poll_interval_seconds,
        symbols=settings.supported_symbols,
    )

    while True:
        if _is_market_open():
            try:
                for sym in settings.supported_symbols:
                    try:
                        await _collect_symbol(sym)
                    except Exception as exc:
                        logger.warning(
                            "Collector cycle error (will retry)",
                            symbol=sym,
                            error=str(exc),
                        )
                    # 3-second gap between symbols to respect Zerodha rate limits
                    await asyncio.sleep(3)
            except Exception as exc:
                logger.warning("Collector outer error (will retry)", error=str(exc))

            # Run alert and signal evaluation on latest data
            try:
                await run_all_symbols()
            except Exception as exc:
                logger.warning("Alert evaluation failed (will retry next cycle)", error=str(exc))

            try:
                await run_signal_engine_cycle()
            except Exception as exc:
                logger.warning("Signal engine failed (will retry next cycle)", error=str(exc))
        else:
            logger.info("Market closed — skipping Zerodha fetch and signal evaluation")

        await asyncio.sleep(settings.poll_interval_seconds)
