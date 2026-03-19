"""
Pure helpers for feature snapshot construction.
"""

from __future__ import annotations

from datetime import datetime

_RANGEBOUND_THRESHOLDS = {
    "5m": 0.0015,
    "30m": 0.0025,
    "60m": 0.0040,
}


def floor_to_minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def merge_bar_ohlc(existing: dict[str, float] | None, price: float) -> dict[str, float]:
    if existing is None:
        return {"open": price, "high": price, "low": price, "close": price}
    return {
        "open": existing["open"],
        "high": max(existing["high"], price),
        "low": min(existing["low"], price),
        "close": price,
    }


def is_price_rangebound(timeframe: str, price_change_pct: float) -> bool:
    threshold = _RANGEBOUND_THRESHOLDS.get(timeframe, 0.0025)
    return abs(price_change_pct) <= threshold
