"""
Feature snapshot builder for historical replay and future signal engines.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.feature_utils import floor_to_minute, is_price_rangebound, merge_bar_ohlc
from app.models.chain_snapshot import ChainSnapshot
from app.models.signal_feature_snapshot import SignalFeatureSnapshot
from app.models.underlying_bar import UnderlyingBar

_TIMEFRAME_WINDOWS = {
    "5m": timedelta(minutes=5),
    "30m": timedelta(minutes=30),
    "60m": timedelta(minutes=60),
}


async def persist_underlying_bar(
    session: AsyncSession,
    symbol: str,
    price: float,
    timestamp: datetime,
) -> None:
    bar_time = floor_to_minute(timestamp)
    stmt = (
        select(UnderlyingBar)
        .where(
            UnderlyingBar.symbol == symbol,
            UnderlyingBar.timeframe == "1m",
            UnderlyingBar.bar_time == bar_time,
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    merged = merge_bar_ohlc(
        {
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
        } if row else None,
        price,
    )
    if row is None:
        session.add(
            UnderlyingBar(
                symbol=symbol,
                timeframe="1m",
                bar_time=bar_time,
                open=merged["open"],
                high=merged["high"],
                low=merged["low"],
                close=merged["close"],
            )
        )
    else:
        row.high = merged["high"]
        row.low = merged["low"]
        row.close = merged["close"]


async def _distinct_timestamps(session: AsyncSession, symbol: str, limit: int = 120) -> list[datetime]:
    rows = (
        await session.execute(
            select(ChainSnapshot.timestamp)
            .where(ChainSnapshot.symbol == symbol)
            .distinct()
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


def _closest_timestamp_at_or_before(timestamps: list[datetime], cutoff: datetime) -> datetime | None:
    for ts in timestamps:
        if ts <= cutoff:
            return ts
    return None


async def _load_chain_rows(session: AsyncSession, symbol: str, ts: datetime) -> list[ChainSnapshot]:
    return (
        await session.execute(
            select(ChainSnapshot)
            .where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp == ts,
            )
            .order_by(ChainSnapshot.strike)
        )
    ).scalars().all()


def _support_resistance(rows: list[ChainSnapshot], spot: float, band_pct: float = 0.03) -> tuple[float | None, float | None]:
    if not rows or spot <= 0:
        return None, None
    band = spot * band_pct
    below = [r for r in rows if float(r.strike) <= spot and abs(float(r.strike) - spot) <= band]
    above = [r for r in rows if float(r.strike) >= spot and abs(float(r.strike) - spot) <= band]
    support = float(max(below, key=lambda row: row.put_oi).strike) if below else None
    resistance = float(max(above, key=lambda row: row.call_oi).strike) if above else None
    return support, resistance


def _aggregate_totals(rows: list[ChainSnapshot]) -> dict[str, Any]:
    if not rows:
        return {
            "price": 0.0,
            "total_call_oi": 0,
            "total_put_oi": 0,
            "total_call_volume": 0,
            "total_put_volume": 0,
        }
    return {
        "price": float(rows[0].underlying_price or 0),
        "total_call_oi": int(sum(int(row.call_oi or 0) for row in rows)),
        "total_put_oi": int(sum(int(row.put_oi or 0) for row in rows)),
        "total_call_volume": int(sum(int(row.call_volume or 0) for row in rows)),
        "total_put_volume": int(sum(int(row.put_volume or 0) for row in rows)),
    }


def _row_map(rows: list[ChainSnapshot]) -> dict[float, ChainSnapshot]:
    return {float(row.strike): row for row in rows}


def _position_buildup(current_price: float, prev_price: float, total_oi: int, prev_total_oi: int) -> str | None:
    price_up = current_price > prev_price
    price_down = current_price < prev_price
    oi_up = total_oi > prev_total_oi
    oi_down = total_oi < prev_total_oi
    if price_up and oi_up:
        return "Long buildup"
    if price_down and oi_up:
        return "Short buildup"
    if price_up and oi_down:
        return "Short covering"
    if price_down and oi_down:
        return "Long unwinding"
    return None


async def build_feature_snapshots_for_symbol(session: AsyncSession, symbol: str) -> int:
    timestamps = await _distinct_timestamps(session, symbol)
    if not timestamps:
        return 0

    latest_ts = timestamps[0]
    latest_rows = await _load_chain_rows(session, symbol, latest_ts)
    if not latest_rows:
        return 0

    latest_agg = _aggregate_totals(latest_rows)
    latest_price = latest_agg["price"]
    support, resistance = _support_resistance(latest_rows, latest_price)

    persisted = 0
    for timeframe, window in _TIMEFRAME_WINDOWS.items():
        prior_cutoff = latest_ts - window
        prev_ts = _closest_timestamp_at_or_before(timestamps[1:], prior_cutoff)
        if prev_ts is None:
            continue

        prev_rows = await _load_chain_rows(session, symbol, prev_ts)
        if not prev_rows:
            continue

        prev_agg = _aggregate_totals(prev_rows)
        prev_price = prev_agg["price"]
        if prev_price <= 0:
            continue

        latest_map = _row_map(latest_rows)
        prev_map = _row_map(prev_rows)

        support_prev = prev_map.get(support) if support is not None else None
        support_now = latest_map.get(support) if support is not None else None
        resistance_prev = prev_map.get(resistance) if resistance is not None else None
        resistance_now = latest_map.get(resistance) if resistance is not None else None

        near_support_put_oi_change = int((support_now.put_oi if support_now else 0) - (support_prev.put_oi if support_prev else 0))
        near_resistance_call_oi_change = int((resistance_now.call_oi if resistance_now else 0) - (resistance_prev.call_oi if resistance_prev else 0))

        total_call_oi = latest_agg["total_call_oi"]
        total_put_oi = latest_agg["total_put_oi"]
        total_call_oi_prev = prev_agg["total_call_oi"]
        total_put_oi_prev = prev_agg["total_put_oi"]
        total_oi = total_call_oi + total_put_oi
        total_oi_prev = total_call_oi_prev + total_put_oi_prev
        total_volume = latest_agg["total_call_volume"] + latest_agg["total_put_volume"]
        prev_total_volume = prev_agg["total_call_volume"] + prev_agg["total_put_volume"]

        price_change_points = round(latest_price - prev_price, 2)
        price_change_pct = round((price_change_points / prev_price), 4) if prev_price else 0.0
        pcr_oi = round(total_put_oi / total_call_oi, 4) if total_call_oi else None

        rangebound_oi_both_sides = near_support_put_oi_change > 0 and near_resistance_call_oi_change > 0
        price_rangebound = is_price_rangebound(timeframe, price_change_pct)
        breakout_flag = resistance is not None and latest_price > resistance * 1.001
        breakdown_flag = support is not None and latest_price < support * 0.999
        trap_warning_flag = (
            breakout_flag and latest_price < prev_price
        ) or (
            breakdown_flag and latest_price > prev_price
        )

        session.add(
            SignalFeatureSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                snapshot_timestamp=latest_ts,
                source_window_start=prev_ts,
                current_price=latest_price,
                prev_price=prev_price,
                price_change_points=price_change_points,
                price_change_pct=price_change_pct,
                total_call_oi=total_call_oi,
                total_put_oi=total_put_oi,
                total_call_oi_prev=total_call_oi_prev,
                total_put_oi_prev=total_put_oi_prev,
                pcr_oi=pcr_oi,
                support_strike=support,
                resistance_strike=resistance,
                near_support_put_oi_change=near_support_put_oi_change,
                near_resistance_call_oi_change=near_resistance_call_oi_change,
                writer_bullish_score=1 if near_support_put_oi_change > abs(near_resistance_call_oi_change) else 0,
                writer_bearish_score=1 if near_resistance_call_oi_change > abs(near_support_put_oi_change) else 0,
                position_buildup=_position_buildup(latest_price, prev_price, total_oi, total_oi_prev),
                volume_spike=bool(prev_total_volume > 0 and total_volume >= prev_total_volume * 1.5),
                price_rangebound=price_rangebound,
                rangebound_oi_both_sides=rangebound_oi_both_sides,
                breakout_flag=breakout_flag,
                breakdown_flag=breakdown_flag,
                trap_warning_flag=trap_warning_flag,
                data_quality_score=100,
            )
        )
        persisted += 1

    return persisted


async def run_feature_snapshot_cycle(session: AsyncSession, symbol: str, timestamp: datetime, price: float) -> int:
    await persist_underlying_bar(session, symbol, price, timestamp)
    return await build_feature_snapshots_for_symbol(session, symbol)
