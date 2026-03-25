"""
Startup freshness checks and stale-data recovery.

Recovery is intentionally conservative:
- If the latest completed trading session is missing or only partially captured,
  we bootstrap the last available chain snapshot from NSE.
- We preserve the source timestamp when the upstream provides it.
- We log heartbeats and gap events so analytics can reason about incomplete days.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.services.market_hours import (
    current_trading_date,
    latest_completed_trading_day,
    needs_completed_day_refresh,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.logging_config import get_logger

    logger = get_logger(__name__)
except Exception:  # pragma: no cover - test fallback when structlog is unavailable
    import logging

    logger = logging.getLogger(__name__)


async def _latest_symbol_snapshot_timestamp(session: AsyncSession, symbol: str) -> datetime | None:
    from sqlalchemy import desc, select

    from app.models.chain_snapshot import ChainSnapshot

    return (
        await session.execute(
            select(ChainSnapshot.timestamp)
            .where(ChainSnapshot.symbol == symbol)
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(1)
        )
    ).scalars().first()


async def _startup_recovery_already_ran(session: AsyncSession, trading_date) -> bool:
    from sqlalchemy import select

    from app.models.collector_heartbeat import CollectorHeartbeat

    row = (
        await session.execute(
            select(CollectorHeartbeat.id)
            .where(
                CollectorHeartbeat.service_name == "startup_recovery",
                CollectorHeartbeat.trading_date == trading_date,
                CollectorHeartbeat.status == "completed",
            )
            .limit(1)
        )
    ).scalars().first()
    return row is not None


def needs_symbol_recovery(latest_ts: datetime | None, now_utc: datetime | None = None) -> bool:
    return needs_completed_day_refresh(latest_ts, now_utc=now_utc)


async def _log_heartbeat(
    session: AsyncSession,
    *,
    trading_date,
    status: str,
    details: str | None = None,
    symbol: str | None = None,
    snapshot_timestamp: datetime | None = None,
) -> None:
    from app.models.collector_heartbeat import CollectorHeartbeat

    session.add(
        CollectorHeartbeat(
            service_name="startup_recovery",
            trading_date=trading_date,
            status=status,
            details=details,
            symbol=symbol,
            snapshot_timestamp=snapshot_timestamp,
        )
    )
    await session.flush()


async def _log_gap_event(
    session: AsyncSession,
    *,
    symbol: str,
    trading_date,
    recovery_status: str,
    latest_known_snapshot_at: datetime | None,
    recovered_snapshot_at: datetime | None,
    notes: str,
) -> None:
    from app.models.data_gap_event import DataGapEvent

    session.add(
        DataGapEvent(
            symbol=symbol,
            trading_date=trading_date,
            gap_kind="missing_completed_day_snapshot",
            recovery_status=recovery_status,
            source_name="NSE_BOOTSTRAP",
            latest_known_snapshot_at=latest_known_snapshot_at,
            recovered_snapshot_at=recovered_snapshot_at,
            notes=notes,
        )
    )
    await session.flush()


async def run_startup_recovery_cycle() -> dict[str, Any]:
    from app.analytics.feature_builder import run_feature_snapshot_cycle
    from app.config import settings
    from app.data_ingestion.data_source_router import NSEDataSource
    from app.data_ingestion.snapshot_store import persist_chain_snapshots
    from app.db.database import AsyncSessionLocal

    now_utc = datetime.now(timezone.utc)
    boot_trading_date = current_trading_date(now_utc)
    target_trading_date = latest_completed_trading_day(now_utc)

    async with AsyncSessionLocal() as session:
        if await _startup_recovery_already_ran(session, boot_trading_date):
            return {
                "status": "skipped",
                "boot_trading_date": str(boot_trading_date),
                "target_trading_date": str(target_trading_date),
                "reason": "already_ran",
            }

        await _log_heartbeat(
            session,
            trading_date=boot_trading_date,
            status="started",
            details=f"target={target_trading_date.isoformat()}",
        )
        await session.commit()

    recovered_symbols: list[str] = []
    skipped_symbols: list[str] = []
    failed_symbols: list[str] = []

    bootstrap_source = NSEDataSource()
    try:
        async with AsyncSessionLocal() as session:
            for symbol in settings.supported_symbols:
                latest_ts = await _latest_symbol_snapshot_timestamp(session, symbol)
                if not needs_symbol_recovery(latest_ts, now_utc):
                    skipped_symbols.append(symbol)
                    continue

                records = await bootstrap_source.fetch_option_chain(symbol)
                if not records:
                    failed_symbols.append(symbol)
                    await _log_gap_event(
                        session,
                        symbol=symbol,
                        trading_date=target_trading_date,
                        recovery_status="unrecovered",
                        latest_known_snapshot_at=latest_ts,
                        recovered_snapshot_at=None,
                        notes="Bootstrap fetch returned no records.",
                    )
                    continue

                recovered_at = await persist_chain_snapshots(session, symbol, records, default_timestamp=now_utc)
                underlying_price = float(records[0].get("underlying_price") or 0.0)
                if recovered_at is not None and underlying_price > 0:
                    await run_feature_snapshot_cycle(session, symbol, recovered_at, underlying_price)
                recovered_symbols.append(symbol)
                await _log_gap_event(
                    session,
                    symbol=symbol,
                    trading_date=target_trading_date,
                    recovery_status="bootstrap_snapshot",
                    latest_known_snapshot_at=latest_ts,
                    recovered_snapshot_at=recovered_at,
                    notes="Recovered last available chain snapshot from NSE bootstrap source.",
                )

            details = (
                f"target={target_trading_date.isoformat()} "
                f"recovered={','.join(recovered_symbols) or '-'} "
                f"skipped={','.join(skipped_symbols) or '-'} "
                f"failed={','.join(failed_symbols) or '-'}"
            )
            await _log_heartbeat(
                session,
                trading_date=boot_trading_date,
                status="completed",
                details=details,
            )
            await session.commit()
    except Exception as exc:
        logger.warning("Startup recovery failed", error=str(exc))
        async with AsyncSessionLocal() as session:
            await _log_heartbeat(
                session,
                trading_date=boot_trading_date,
                status="failed",
                details=str(exc),
            )
            await session.commit()
        return {
            "status": "failed",
            "boot_trading_date": str(boot_trading_date),
            "target_trading_date": str(target_trading_date),
            "error": str(exc),
        }
    finally:
        await bootstrap_source.close()

    logger.info(
        "Startup recovery completed",
        boot_trading_date=str(boot_trading_date),
        target_trading_date=str(target_trading_date),
        recovered=recovered_symbols,
        skipped=skipped_symbols,
        failed=failed_symbols,
    )
    return {
        "status": "completed",
        "boot_trading_date": str(boot_trading_date),
        "target_trading_date": str(target_trading_date),
        "recovered_symbols": recovered_symbols,
        "skipped_symbols": skipped_symbols,
        "failed_symbols": failed_symbols,
    }
