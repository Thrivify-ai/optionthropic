"""
Quant calibration context helpers.

This module keeps the context math mostly pure so we can test segmentation
and risk labeling without touching the live signal engines.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
from statistics import pstdev
from typing import TYPE_CHECKING, Any

from app.services.market_hours import to_ist

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_WINDOWS = (
    ("OPENING", dtime(9, 0), dtime(10, 15)),
    ("MIDDAY", dtime(10, 15), dtime(13, 30)),
    ("CLOSING", dtime(13, 30), dtime(15, 30)),
)

_VOL_THRESHOLDS: dict[str, tuple[float, float]] = {
    "NIFTY": (20.0, 45.0),
    "BANKNIFTY": (45.0, 90.0),
    "SENSEX": (35.0, 80.0),
}

_DEFAULT_VOL_THRESHOLDS = (25.0, 50.0)


def session_bucket(entry_time: datetime) -> str:
    current = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc)
    now_ist = to_ist(current)
    if now_ist.weekday() > 4:
        return "CLOSED"
    for label, start, end in _SESSION_WINDOWS:
        if start <= now_ist.time() < end:
            return label
    return "CLOSED"


def expiry_bucket(days_to_expiry: int | None) -> str | None:
    if days_to_expiry is None:
        return None
    if days_to_expiry <= 0:
        return "0DTE"
    if days_to_expiry == 1:
        return "1DTE"
    if days_to_expiry <= 5:
        return "2_5DTE"
    return "GT5DTE"


def classify_underlying_outcome(signal: str, entry_price: float | None, later_price: float | None) -> str:
    if entry_price is None or later_price is None:
        return "Unknown"
    move = later_price - entry_price
    if signal == "Buy CE" and move > 0:
        return "Won"
    if signal == "Buy CE" and move < 0:
        return "Lost"
    if signal == "Buy PE" and move < 0:
        return "Won"
    if signal == "Buy PE" and move > 0:
        return "Lost"
    return "Unknown"


def classify_option_outcome(entry_ltp: float | None, later_ltp: float | None) -> str:
    if entry_ltp is None or later_ltp is None:
        return "Unknown"
    move = later_ltp - entry_ltp
    if move > 0:
        return "Won"
    if move < 0:
        return "Lost"
    return "Unknown"


def classify_vol_regime(
    symbol: str,
    *,
    quick_momentum: float | None = None,
    five_min_change_points: float | None = None,
) -> str:
    low, high = _VOL_THRESHOLDS.get(symbol.upper(), _DEFAULT_VOL_THRESHOLDS)
    amplitude = max(abs(float(quick_momentum or 0.0)), abs(float(five_min_change_points or 0.0)))
    if amplitude <= 0:
        return "NORMAL"
    if amplitude >= high:
        return "HIGH"
    if amplitude <= low:
        return "LOW"
    return "NORMAL"


def classify_breakout_class(
    *,
    signal: str,
    breakout: bool,
    breakdown: bool,
    support: float | None,
    resistance: float | None,
    current_price: float | None,
    momentum: float | None,
    trap_detected: bool,
) -> str:
    if trap_detected:
        return "FAILED_BREAK"
    if signal == "Buy CE":
        if breakout and resistance is not None and current_price is not None:
            overshoot = current_price - resistance
            if overshoot > max(abs(float(momentum or 0.0)) * 0.2, 8.0):
                return "CLEAN_BREAK"
            return "RETEST_BREAK"
        return "MIDRANGE_IMPULSE"
    if signal == "Buy PE":
        if breakdown and support is not None and current_price is not None:
            overshoot = support - current_price
            if overshoot > max(abs(float(momentum or 0.0)) * 0.2, 8.0):
                return "CLEAN_BREAK"
            return "RETEST_BREAK"
        return "MIDRANGE_IMPULSE"
    return "NO_BREAK"


def score_short_covering_risk(
    *,
    signal: str,
    call_oi_delta: float | None,
    put_oi_delta: float | None,
    breakout: bool,
    breakdown: bool,
    volume_spike: bool,
    writer_support: bool,
) -> int:
    score = 0
    call_oi_delta = float(call_oi_delta or 0.0)
    put_oi_delta = float(put_oi_delta or 0.0)

    if signal == "Buy CE":
        if call_oi_delta < 0 and put_oi_delta <= 0:
            score += 45
        elif call_oi_delta < 0 and put_oi_delta < abs(call_oi_delta) * 0.2:
            score += 25
        if breakout and not volume_spike:
            score += 20
        if not writer_support:
            score += 15

    if signal == "Buy PE":
        if put_oi_delta < 0 and call_oi_delta <= 0:
            score += 45
        elif put_oi_delta < 0 and call_oi_delta < abs(put_oi_delta) * 0.2:
            score += 25
        if breakdown and not volume_spike:
            score += 20
        if not writer_support:
            score += 15

    return max(0, min(100, score))


def score_trap(
    *,
    trap_detected: bool,
    rangebound: bool,
    breakout_class: str,
) -> int:
    if trap_detected:
        return 100
    score = 0
    if breakout_class == "FAILED_BREAK":
        score += 75
    if rangebound:
        score += 20
    return min(100, score)


def classify_regime_label(
    *,
    engine: str,
    signal: str,
    outlook: str | None,
    state: str | None,
    entry_ready: bool,
    rangebound: bool,
    trap_detected: bool,
    expiry_bucket_value: str | None,
    breakout_class: str,
) -> str:
    if trap_detected:
        return "REVERSAL"
    if rangebound:
        return "RANGE"
    if expiry_bucket_value == "0DTE" and not entry_ready:
        return "EXPIRY_PIN"
    if breakout_class in {"CLEAN_BREAK", "RETEST_BREAK"}:
        if signal == "Buy CE":
            return "TREND_UP"
        if signal == "Buy PE":
            return "TREND_DOWN"
    if engine.upper() == "MAIN" and outlook in {"Bullish", "Bearish"}:
        if state in {"setup", "watch"}:
            return "TRANSITION"
        return "TREND_UP" if outlook == "Bullish" else "TREND_DOWN"
    if signal == "Buy CE":
        return "TREND_UP"
    if signal == "Buy PE":
        return "TREND_DOWN"
    return "RANGE"


def wall_shift_score(
    current_support: float | None,
    previous_support: float | None,
    current_resistance: float | None,
    previous_resistance: float | None,
) -> int:
    score = 0
    if current_support is not None and previous_support is not None:
        score += int(abs(current_support - previous_support))
    if current_resistance is not None and previous_resistance is not None:
        score += int(abs(current_resistance - previous_resistance))
    return min(100, score)


async def get_chain_timing_metrics(
    session: AsyncSession,
    symbol: str,
    reference_time: datetime,
    *,
    sample_size: int = 6,
) -> tuple[float | None, float | None]:
    from sqlalchemy import desc, func, select
    from app.models.chain_snapshot import ChainSnapshot

    reference = reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)
    timestamps = (
        await session.execute(
            select(func.distinct(ChainSnapshot.timestamp))
            .where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp <= reference,
            )
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(sample_size)
        )
    ).scalars().all()
    if not timestamps:
        return None, None

    latest = timestamps[0]
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    freshness = round(max(0.0, (reference - latest).total_seconds()), 2)

    if len(timestamps) < 3:
        return freshness, 0.0

    spacing = []
    for newer, older in zip(timestamps, timestamps[1:]):
        n = newer if newer.tzinfo else newer.replace(tzinfo=timezone.utc)
        o = older if older.tzinfo else older.replace(tzinfo=timezone.utc)
        spacing.append(abs((n - o).total_seconds()))
    return freshness, round(float(pstdev(spacing)), 2)


async def get_nearest_expiry_context(
    session: AsyncSession,
    symbol: str,
    reference_time: datetime,
) -> tuple[int | None, bool, str | None]:
    from sqlalchemy import select
    from app.models.options_snapshot import OptionsSnapshot

    reference = reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)
    ref_date = to_ist(reference).date()
    expiries = (
        await session.execute(
            select(OptionsSnapshot.expiry)
            .where(
                OptionsSnapshot.symbol == symbol,
                OptionsSnapshot.expiry >= ref_date,
            )
            .group_by(OptionsSnapshot.expiry)
            .order_by(OptionsSnapshot.expiry.asc())
            .limit(3)
        )
    ).scalars().all()
    if not expiries:
        return None, False, None

    nearest = expiries[0]
    days = (nearest - ref_date).days
    return days, days == 0, expiry_bucket(days)


async def get_open_gap_pct(
    session: AsyncSession,
    symbol: str,
    reference_time: datetime,
) -> float | None:
    from sqlalchemy import select
    from app.models.underlying_bar import UnderlyingBar

    reference = reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)
    ref_ist = to_ist(reference)
    today = ref_ist.date()
    prior_day = today - timedelta(days=1)

    today_rows = (
        await session.execute(
            select(UnderlyingBar)
            .where(
                UnderlyingBar.symbol == symbol,
                UnderlyingBar.timeframe == "1m",
            )
            .order_by(UnderlyingBar.bar_time.desc())
            .limit(200)
        )
    ).scalars().all()
    if not today_rows:
        return None

    first_today = None
    last_prior = None
    for row in reversed(today_rows):
        bar_time = row.bar_time if row.bar_time.tzinfo else row.bar_time.replace(tzinfo=timezone.utc)
        bar_ist = to_ist(bar_time)
        if bar_ist.date() == today and first_today is None:
            first_today = float(row.open)
        if bar_ist.date() == prior_day:
            last_prior = float(row.close)

    if first_today is None or last_prior in (None, 0):
        return None
    return round((first_today - last_prior) / last_prior * 100, 3)


async def get_underlying_price_at_time(
    session: AsyncSession,
    symbol: str,
    target: datetime,
    *,
    tolerance_minutes: int,
) -> float | None:
    from sqlalchemy import desc, select
    from app.models.chain_snapshot import ChainSnapshot

    window = timedelta(minutes=tolerance_minutes)
    rows = (
        await session.execute(
            select(ChainSnapshot.underlying_price, ChainSnapshot.timestamp)
            .where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp >= target - window,
                ChainSnapshot.timestamp <= target + window,
            )
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(50)
        )
    ).all()
    if not rows:
        return None

    target_ts = target.timestamp()
    best_price = None
    best_diff = float("inf")
    for price, ts in rows:
        if ts is None or price is None:
            continue
        comp = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        diff = abs(comp.timestamp() - target_ts)
        if diff < best_diff:
            best_diff = diff
            best_price = float(price)
    return best_price
