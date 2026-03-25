"""
Cached dashboard overview helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_engine.market_explainer import get_market_summary_payload
from app.analytics.dashboard_view_utils import mark_payload_stale, serialize_trading_signal_payload
from app.analytics.gamma_detection import compute_gamma_walls
from app.analytics.liquidity_trap_detection import detect_liquidity_traps
from app.analytics.max_pain_detection import compute_max_pain
from app.analytics.options_analysis import compute_pcr, compute_support_resistance
from app.analytics.options_flow_detection import detect_options_flow
from app.analytics.quick_signal import get_quick_signal
from app.analytics.trade_manager import get_latest_trade_row, get_open_trade_row, serialize_trade_summary
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.models.dashboard_snapshot_cache import DashboardSnapshotCache
from app.models.trading_signal import TradingSignalRow
from app.services.market_hours import dashboard_cache_ttl_seconds, should_refresh_intraday_caches
from app.services.runtime_cache import runtime_cache

DASHBOARD_OVERVIEW_CACHE_KEY = "dashboard:overview:v1"


async def build_dashboard_snapshot_for_symbol(session: AsyncSession, symbol: str) -> dict[str, Any]:
    options_chain_pcr = await compute_pcr(session, symbol)
    gamma = await compute_gamma_walls(session, symbol)
    max_pain = await compute_max_pain(session, symbol)
    traps = await detect_liquidity_traps(session, symbol)
    flow = await detect_options_flow(session, symbol, top_n=20)
    quick_signal = await get_quick_signal(session, symbol)
    support_resistance = await compute_support_resistance(session, symbol)
    trading_row = (
        await session.execute(
            select(TradingSignalRow)
            .where(TradingSignalRow.symbol == symbol)
            .order_by(TradingSignalRow.generated_at.desc())
            .limit(1)
        )
    ).scalars().first()
    trade_row = await get_open_trade_row(session, engine="MAIN", symbol=symbol)
    if trade_row is None:
        trade_row = await get_latest_trade_row(session, engine="MAIN", symbol=symbol)

    source_timestamp = options_chain_pcr.get("latest_snapshot_at") or support_resistance.get("timestamp")
    return {
        "symbol": symbol,
        "options_chain": {
            "pcr": options_chain_pcr,
            "support_resistance": support_resistance,
        },
        "gamma_walls": gamma,
        "max_pain": max_pain,
        "liquidity_traps": traps,
        "options_flow": flow,
        "trading_signal": serialize_trading_signal_payload(
            trading_row,
            serialize_trade_summary(trade_row),
        ),
        "quick_signal": quick_signal,
        "source_timestamp": source_timestamp,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def _cache_dashboard_overview(payload: dict[str, Any], now_utc: datetime | None = None) -> None:
    await runtime_cache.set_json(
        DASHBOARD_OVERVIEW_CACHE_KEY,
        payload,
        ttl_seconds=dashboard_cache_ttl_seconds(now_utc),
    )


async def _compose_overview_payload(
    session: AsyncSession,
    *,
    market_open: bool,
    symbol_payloads: dict[str, dict[str, Any]] | None = None,
    build_missing: bool,
    refresh_ai: bool,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    symbols: dict[str, Any] = {}
    provided = symbol_payloads or {}

    for symbol in settings.supported_symbols:
        payload = provided.get(symbol)
        if payload is None:
            cache_row = await session.get(DashboardSnapshotCache, symbol)
            if cache_row is not None:
                payload = (
                    mark_payload_stale(
                        cache_row.payload,
                        cache_row.generated_at,
                        now=now,
                        max_age=timedelta(seconds=dashboard_cache_ttl_seconds(now)),
                    )
                    if market_open
                    else dict(cache_row.payload)
                )
            elif build_missing:
                payload = await build_dashboard_snapshot_for_symbol(session, symbol)
            else:
                payload = {"symbol": symbol}

        payload["ai_summary"] = await get_market_summary_payload(
            session,
            symbol,
            allow_stale=not market_open,
            refresh_if_missing=market_open and refresh_ai,
        )
        symbols[symbol] = payload

    return {
        "symbols": symbols,
        "generated_at": now.isoformat(),
        "market_open": market_open,
    }


async def refresh_dashboard_snapshot_cache() -> None:
    market_open = should_refresh_intraday_caches()
    async with AsyncSessionLocal() as session:
        snapshots: dict[str, dict[str, Any]] = {}
        for symbol in settings.supported_symbols:
            payload = await build_dashboard_snapshot_for_symbol(session, symbol)
            snapshots[symbol] = payload
            row = await session.get(DashboardSnapshotCache, symbol)
            source_ts = payload.get("source_timestamp")
            parsed_source_ts = None
            if isinstance(source_ts, str):
                try:
                    parsed_source_ts = datetime.fromisoformat(source_ts)
                except ValueError:
                    parsed_source_ts = None

            if row is None:
                session.add(
                    DashboardSnapshotCache(
                        symbol=symbol,
                        payload=payload,
                        source_timestamp=parsed_source_ts,
                        generated_at=datetime.now(timezone.utc),
                    )
                )
            else:
                row.payload = payload
                row.source_timestamp = parsed_source_ts
                row.generated_at = datetime.now(timezone.utc)
        await session.commit()

        overview = await _compose_overview_payload(
            session,
            market_open=market_open,
            symbol_payloads=snapshots,
            build_missing=False,
            refresh_ai=False,
        )
        await _cache_dashboard_overview(overview)


async def warm_dashboard_overview_cache(force_refresh: bool = False) -> dict[str, Any]:
    market_open = should_refresh_intraday_caches()
    async with AsyncSessionLocal() as session:
        if force_refresh:
            await refresh_dashboard_snapshot_cache()
            cached = await runtime_cache.get_json(DASHBOARD_OVERVIEW_CACHE_KEY)
            if cached is not None:
                return cached

        overview = await _compose_overview_payload(
            session,
            market_open=market_open,
            build_missing=market_open,
            refresh_ai=False,
        )
        await _cache_dashboard_overview(overview)
        return overview


async def get_dashboard_overview(session: AsyncSession) -> dict[str, Any]:
    cached = await runtime_cache.get_json(DASHBOARD_OVERVIEW_CACHE_KEY)
    if isinstance(cached, dict) and cached.get("symbols"):
        return cached

    market_open = should_refresh_intraday_caches()
    overview = await _compose_overview_payload(
        session,
        market_open=market_open,
        build_missing=True,
        refresh_ai=True,
    )
    await _cache_dashboard_overview(overview)
    return overview
