"""
Market-hours helpers for Indian index trading.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone

try:
    from app.config import settings
except Exception:  # pragma: no cover - test fallback when settings deps are unavailable
    class _FallbackSettings:
        dashboard_cache_ttl_market_open_seconds = 15
        dashboard_cache_ttl_market_closed_seconds = 14400
        ai_cache_ttl_market_open_seconds = 300
        ai_cache_ttl_market_closed_seconds = 21600

    settings = _FallbackSettings()

IST_OFFSET = timedelta(hours=5, minutes=30)
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)
MARKET_WEEKDAYS = {0, 1, 2, 3, 4}


def to_ist(now_utc: datetime | None = None) -> datetime:
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone(IST_OFFSET))


def is_indian_market_open(now_utc: datetime | None = None) -> bool:
    now_ist = to_ist(now_utc)
    return now_ist.weekday() in MARKET_WEEKDAYS and MARKET_OPEN <= now_ist.time() <= MARKET_CLOSE


def dashboard_cache_ttl_seconds(now_utc: datetime | None = None) -> int:
    if is_indian_market_open(now_utc):
        return settings.dashboard_cache_ttl_market_open_seconds
    return settings.dashboard_cache_ttl_market_closed_seconds


def ai_cache_ttl_seconds(now_utc: datetime | None = None) -> int:
    if is_indian_market_open(now_utc):
        return settings.ai_cache_ttl_market_open_seconds
    return settings.ai_cache_ttl_market_closed_seconds


def should_refresh_intraday_caches(now_utc: datetime | None = None) -> bool:
    return is_indian_market_open(now_utc)
