"""
Shared intraday volatility helpers for signal quality.

The signal engines use these profiles to avoid fixed-point thresholds across
quiet and fast sessions. The goal is not to predict direction here, only to
scale entry/exit expectations to the current tape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_BASELINE_ABS_MOVE_1M = {
    "NIFTY": 9.0,
    "BANKNIFTY": 20.0,
    "SENSEX": 24.0,
}


@dataclass(frozen=True)
class IntradayVolatilityProfile:
    symbol: str
    baseline_abs_move_1m: float
    avg_abs_move_1m: float
    avg_true_range_1m: float
    realized_move_5m: float
    ratio_to_baseline: float
    sample_size: int


def _baseline(symbol: str) -> float:
    return _BASELINE_ABS_MOVE_1M.get(symbol.upper(), 10.0)


def scale_threshold(
    base_value: float,
    profile: IntradayVolatilityProfile | None,
    *,
    multiplier: float,
    floor_ratio: float = 0.8,
    ceiling_ratio: float = 1.8,
) -> float:
    if profile is None:
        return round(float(base_value), 2)

    volatility_component = profile.avg_abs_move_1m * multiplier
    lower_bound = float(base_value) * floor_ratio
    upper_bound = float(base_value) * ceiling_ratio
    return round(max(lower_bound, min(upper_bound, volatility_component)), 2)


def scale_trade_thresholds(
    *,
    base_success: float,
    base_stop: float,
    volatility_ratio: float | None,
    event_risk: bool = False,
) -> tuple[float, float]:
    ratio = float(volatility_ratio or 1.0)
    ratio = max(0.85, min(1.45, ratio))
    if event_risk:
        ratio = min(1.55, ratio * 1.08)

    success = round(base_success * ratio, 2)
    stop = round(base_stop * max(0.85, min(1.35, ratio * 0.95)), 2)
    return success, stop


async def load_intraday_volatility_profile(
    session: AsyncSession,
    symbol: str,
    *,
    timeframe: str = "1m",
    sample_size: int = 18,
) -> IntradayVolatilityProfile | None:
    from sqlalchemy import desc, select
    from app.models.underlying_bar import UnderlyingBar

    rows = (
        await session.execute(
            select(UnderlyingBar)
            .where(
                UnderlyingBar.symbol == symbol.upper(),
                UnderlyingBar.timeframe == timeframe,
            )
            .order_by(desc(UnderlyingBar.bar_time))
            .limit(sample_size)
        )
    ).scalars().all()

    if len(rows) < 4:
        return None

    ordered = list(reversed(rows))
    abs_moves: list[float] = []
    true_ranges: list[float] = []

    previous_close = None
    for row in ordered:
        close_price = float(row.close)
        high_price = float(row.high)
        low_price = float(row.low)
        if previous_close is not None:
            abs_moves.append(abs(close_price - previous_close))
        true_ranges.append(max(high_price - low_price, abs(high_price - close_price), abs(low_price - close_price)))
        previous_close = close_price

    if not abs_moves:
        return None

    latest_close = float(ordered[-1].close)
    reference_close = float(ordered[max(0, len(ordered) - 6)].close)
    realized_move_5m = round(abs(latest_close - reference_close), 2)
    avg_abs_move_1m = round(sum(abs_moves) / len(abs_moves), 2)
    avg_true_range_1m = round(sum(true_ranges) / len(true_ranges), 2)
    baseline_abs_move_1m = _baseline(symbol)
    ratio = round(avg_abs_move_1m / max(1.0, baseline_abs_move_1m), 3)

    return IntradayVolatilityProfile(
        symbol=symbol.upper(),
        baseline_abs_move_1m=baseline_abs_move_1m,
        avg_abs_move_1m=avg_abs_move_1m,
        avg_true_range_1m=avg_true_range_1m,
        realized_move_5m=realized_move_5m,
        ratio_to_baseline=ratio,
        sample_size=len(ordered),
    )
