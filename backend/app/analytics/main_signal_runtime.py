"""
Runtime structure context for long-signal v3.

We enrich the options-derived feature snapshots with a small amount of market
structure context from stored underlying bars and saved critical news. That
lets the long engine reason about finish bias and trade management without
changing the existing snapshot schema.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.analytics.market_scanner import fetch_market_breadth_snapshot
from app.analytics.quant_signal_context import get_nearest_expiry_context, session_bucket
from app.analytics.volatility_profile import load_intraday_volatility_profile
from app.services.market_hours import IST_OFFSET, MARKET_CLOSE, MARKET_OPEN, previous_trading_day, to_ist

try:
    from sqlalchemy.ext.asyncio import AsyncSession
except Exception:  # pragma: no cover - test fallback when SQLAlchemy is unavailable
    AsyncSession = object  # type: ignore[assignment]


@dataclass(frozen=True)
class LongSignalContext:
    session_vwap: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    previous_day_high: float | None = None
    previous_day_low: float | None = None
    previous_day_close: float | None = None
    session_bucket: str | None = None
    news_impact_score: int = 0
    event_profile: str = "normal"
    days_to_expiry: int | None = None
    expiry_bucket: str | None = None
    is_expiry_day: bool = False
    breadth_score: int = 0
    breadth_direction: str | None = None
    breadth_reason: str | None = None
    breadth_available: bool = False
    intraday_volatility_ratio: float = 1.0
    avg_abs_move_1m: float | None = None
    opening_range_width_points: float | None = None


def _session_boundary_utc(day: date, boundary) -> datetime:
    ts_ist = datetime.combine(day, boundary, tzinfo=timezone(IST_OFFSET))
    return ts_ist.astimezone(timezone.utc)


async def _bars_for_window(
    session: AsyncSession,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
) -> list[UnderlyingBar]:
    from sqlalchemy import select
    from app.models.underlying_bar import UnderlyingBar

    return (
        await session.execute(
            select(UnderlyingBar)
            .where(
                UnderlyingBar.symbol == symbol,
                UnderlyingBar.timeframe == "1m",
                UnderlyingBar.bar_time >= start_utc,
                UnderlyingBar.bar_time <= end_utc,
            )
            .order_by(UnderlyingBar.bar_time.asc(), UnderlyingBar.id.asc())
        )
    ).scalars().all()


def _session_vwap_proxy(rows: list[UnderlyingBar]) -> float | None:
    if not rows:
        return None
    typical_prices = [
        (float(row.high) + float(row.low) + float(row.close)) / 3.0
        for row in rows
    ]
    return round(sum(typical_prices) / len(typical_prices), 2)


def _opening_range(rows: list[UnderlyingBar], minutes: int = 15) -> tuple[float | None, float | None]:
    if not rows:
        return None, None
    opening_rows = rows[:minutes]
    return (
        round(max(float(row.high) for row in opening_rows), 2),
        round(min(float(row.low) for row in opening_rows), 2),
    )


def _previous_day_levels(rows: list[UnderlyingBar]) -> tuple[float | None, float | None, float | None]:
    if not rows:
        return None, None, None
    high = round(max(float(row.high) for row in rows), 2)
    low = round(min(float(row.low) for row in rows), 2)
    close = round(float(rows[-1].close), 2)
    return high, low, close


def _news_affects_symbol(symbol: str, affected_symbols: list[str] | None) -> bool:
    affected = {str(item).upper() for item in (affected_symbols or [])}
    symbol_key = symbol.upper()
    if symbol_key in affected:
        return True
    if symbol_key in {"NIFTY", "BANKNIFTY", "SENSEX"}:
        return bool(affected & {"NIFTY", "BANKNIFTY", "SENSEX"})
    return False


async def recent_news_impact_score(
    session: AsyncSession,
    symbol: str,
    reference_time: datetime,
) -> int:
    from sqlalchemy import desc, select
    from app.models.global_news_alert import GlobalNewsAlert

    cutoff = reference_time - timedelta(hours=8)
    rows = (
        await session.execute(
            select(GlobalNewsAlert)
            .where(
                GlobalNewsAlert.is_critical.is_(True),
                GlobalNewsAlert.fetched_at >= cutoff,
            )
            .order_by(desc(GlobalNewsAlert.impact_score), desc(GlobalNewsAlert.fetched_at))
            .limit(40)
        )
    ).scalars().all()
    best = 0.0
    for row in rows:
        if _news_affects_symbol(symbol, row.affected_symbols):
            raw_score = float(row.impact_score or 0)
            fetched_at = row.fetched_at
            if fetched_at is None:
                continue
            fetched = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
            age_minutes = max(0.0, (reference_time - fetched).total_seconds() / 60.0)
            # News impact should decay through the session; stale global headlines
            # should not suppress valid signals for hours.
            decay = math.exp(-age_minutes / 150.0)
            decayed = raw_score * decay
            if age_minutes <= 40:
                decayed = max(decayed, raw_score * 0.9)
            best = max(best, decayed)
    return int(max(0, min(100, round(best))))


async def load_long_signal_context(
    session: AsyncSession,
    symbol: str,
    reference_time: datetime,
) -> LongSignalContext:
    reference = reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)
    reference_ist = to_ist(reference)
    trading_day = reference_ist.date()
    previous_day = previous_trading_day(trading_day)

    today_start = _session_boundary_utc(trading_day, MARKET_OPEN)
    today_end = min(reference, _session_boundary_utc(trading_day, MARKET_CLOSE))
    prev_start = _session_boundary_utc(previous_day, MARKET_OPEN)
    prev_end = _session_boundary_utc(previous_day, MARKET_CLOSE)

    today_rows = await _bars_for_window(session, symbol, today_start, today_end)
    previous_rows = await _bars_for_window(session, symbol, prev_start, prev_end)

    session_vwap = _session_vwap_proxy(today_rows)
    opening_range_high, opening_range_low = _opening_range(today_rows)
    previous_day_high, previous_day_low, previous_day_close = _previous_day_levels(previous_rows)
    news_impact = await recent_news_impact_score(session, symbol, reference)
    breadth = await fetch_market_breadth_snapshot(symbol)
    volatility_profile = await load_intraday_volatility_profile(session, symbol)
    days_to_expiry, is_expiry_day, expiry_bucket_value = await get_nearest_expiry_context(
        session,
        symbol,
        reference,
    )

    profile = "normal"
    if news_impact >= 85 and is_expiry_day:
        profile = "event_expiry"
    elif news_impact >= 85:
        profile = "event"
    elif is_expiry_day or expiry_bucket_value == "1DTE":
        profile = "expiry"

    return LongSignalContext(
        session_vwap=session_vwap,
        opening_range_high=opening_range_high,
        opening_range_low=opening_range_low,
        previous_day_high=previous_day_high,
        previous_day_low=previous_day_low,
        previous_day_close=previous_day_close,
        session_bucket=session_bucket(reference),
        news_impact_score=int(news_impact),
        event_profile=profile,
        days_to_expiry=days_to_expiry,
        expiry_bucket=expiry_bucket_value,
        is_expiry_day=is_expiry_day,
        breadth_score=int(breadth.breadth_score),
        breadth_direction=breadth.direction_bias,
        breadth_reason=breadth.reason,
        breadth_available=bool(breadth.available),
        intraday_volatility_ratio=float(volatility_profile.ratio_to_baseline) if volatility_profile is not None else 1.0,
        avg_abs_move_1m=float(volatility_profile.avg_abs_move_1m) if volatility_profile is not None else None,
        opening_range_width_points=(
            round(float(opening_range_high - opening_range_low), 2)
            if opening_range_high is not None and opening_range_low is not None
            else None
        ),
    )
