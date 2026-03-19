"""
Pro Quick Signal — 10-second tick-based quick signal.

Reuses concepts from quick_signal_engine but does NOT modify it.
Uses 10s aggregated tick data. Reads OI/breakout from chain_snapshot when needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chain_snapshot import ChainSnapshot
from app.services.tick_stream import get_latest_ticks, get_price_10s_ago

# 10s momentum thresholds (points) — relaxed to catch more moves
_THRESH = {"NIFTY": 10, "BANKNIFTY": 22, "SENSEX": 28}


async def run_pro_quick_signal(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """
    Pro quick signal: 10s tick momentum when available, else chain_snapshot 1m fallback.
    """
    symbol = symbol.upper()
    ticks = get_latest_ticks()
    tick_data = ticks.get(symbol)
    price_now = tick_data.get("price") if tick_data else None
    if price_now is None:
        price_now = await _latest_price_from_snap(session, symbol)
    if price_now is None:
        return _wait_out(symbol, "No price data")

    price_10s = get_price_10s_ago(symbol)
    momentum_10s = round(price_now - price_10s, 2) if price_10s else None

    # Fallback: when no 10s tick history, use chain snapshot delta (~45–90s)
    if momentum_10s is None:
        momentum_10s = await _snap_momentum(session, symbol, price_now)
        momentum_10s = round(momentum_10s, 2) if momentum_10s is not None else None

    thresh = _THRESH.get(symbol, 20)
    bull = momentum_10s is not None and momentum_10s >= thresh
    bear = momentum_10s is not None and momentum_10s <= -thresh

    support, resistance, call_oi_delta, put_oi_delta, vol_spike = await _snap_context(
        session, symbol, price_now
    )

    breakout = resistance and price_now > resistance * 1.001
    breakdown = support and price_now < support * 0.999
    call_oi_dec = call_oi_delta < 0
    put_oi_dec = put_oi_delta < 0

    if bull and (breakout or vol_spike) and call_oi_dec:
        return {
            "symbol": symbol,
            "quick_signal": "Buy CE",
            "momentum_10s": momentum_10s,
            "reason": f"+{momentum_10s:.0f} pts (10s) · breakout/volume · call OI falling",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    if bear and (breakdown or vol_spike) and put_oi_dec:
        return {
            "symbol": symbol,
            "quick_signal": "Buy PE",
            "momentum_10s": momentum_10s,
            "reason": f"{momentum_10s:.0f} pts (10s) · breakdown/volume · put OI falling",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    if bull:
        return {
            "symbol": symbol,
            "quick_signal": "Buy CE",
            "momentum_10s": momentum_10s,
            "reason": f"+{momentum_10s:.0f} pts (10s) bullish momentum",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    if bear:
        return {
            "symbol": symbol,
            "quick_signal": "Buy PE",
            "momentum_10s": momentum_10s,
            "reason": f"{momentum_10s:.0f} pts (10s) bearish momentum",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    return _wait_out(
        symbol,
        f"Momentum {momentum_10s or 0:+.0f} below ±{thresh} pts",
        momentum_10s=momentum_10s,
    )


async def _latest_price_from_snap(session: AsyncSession, symbol: str) -> float | None:
    """Fallback price from latest chain snapshot when ticks unavailable."""
    row = (
        await session.execute(
            select(ChainSnapshot.underlying_price)
            .where(ChainSnapshot.symbol == symbol)
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(1)
        )
    ).scalars().first()
    return float(row) if row is not None else None


async def _snap_momentum(session: AsyncSession, symbol: str, price_now: float) -> float | None:
    """Momentum from chain snapshot: price_now - prev timestamp. Used when tick 10s unavailable."""
    rows = (
        await session.execute(
            select(ChainSnapshot.underlying_price, ChainSnapshot.timestamp)
            .where(ChainSnapshot.symbol == symbol)
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(3)
        )
    ).all()
    if len(rows) < 2:
        return None
    prev_price = rows[1][0]
    return float(price_now) - float(prev_price) if prev_price else None


async def _snap_context(session: AsyncSession, symbol: str, spot: float):
    """Get support, resistance, OI deltas, volume spike from latest snapshots."""
    rows = (
        await session.execute(
            select(func.distinct(ChainSnapshot.timestamp))
            .where(ChainSnapshot.symbol == symbol)
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(5)
        )
    ).scalars().all()
    timestamps = sorted(rows, reverse=True)
    if len(timestamps) < 2:
        return None, None, 0.0, 0.0, False

    ts_now = timestamps[0]
    ts_prev = timestamps[1]

    curr = (
        await session.execute(
            select(
                func.sum(ChainSnapshot.call_oi),
                func.sum(ChainSnapshot.put_oi),
                func.sum(ChainSnapshot.call_volume),
                func.sum(ChainSnapshot.put_volume),
            ).where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp == ts_now,
            )
        )
    ).one_or_none()
    prev = (
        await session.execute(
            select(
                func.sum(ChainSnapshot.call_oi),
                func.sum(ChainSnapshot.put_oi),
                func.sum(ChainSnapshot.call_volume),
                func.sum(ChainSnapshot.put_volume),
            ).where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp == ts_prev,
            )
        )
    ).one_or_none()

    call_oi_d = (curr[0] or 0) - (prev[0] or 0) if curr and prev else 0
    put_oi_d = (curr[1] or 0) - (prev[1] or 0) if curr and prev else 0
    curr_vol = (curr[2] or 0) + (curr[3] or 0) if curr else 0
    prev_vol = (prev[2] or 0) + (prev[3] or 0) if prev else 0
    vol_spike = prev_vol > 0 and curr_vol >= 1.5 * prev_vol

    band = spot * 0.02
    chain_now = (
        await session.execute(
            select(ChainSnapshot)
            .where(ChainSnapshot.symbol == symbol, ChainSnapshot.timestamp == ts_now)
        )
    ).scalars().all()
    support = resistance = None
    if chain_now and spot > 0:
        below = [r for r in chain_now if float(r.strike) <= spot and abs(float(r.strike) - spot) <= band]
        above = [r for r in chain_now if float(r.strike) >= spot and abs(float(r.strike) - spot) <= band]
        if below:
            support = float(max(below, key=lambda r: r.put_oi).strike)
        if above:
            resistance = float(max(above, key=lambda r: r.call_oi).strike)

    return support, resistance, call_oi_d, put_oi_d, vol_spike


def _wait_out(symbol: str, reason: str, momentum_10s: float | None = None) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "quick_signal": "Wait",
        "momentum_10s": momentum_10s,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
