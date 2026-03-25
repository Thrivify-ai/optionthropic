"""
Market-hours helpers for Indian index trading.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone

try:
    from app.config import settings
except Exception:  # pragma: no cover - test fallback when settings deps are unavailable
    class _FallbackSettings:
        dashboard_cache_ttl_market_open_seconds = 15
        dashboard_cache_ttl_market_closed_seconds = 14400
        ai_cache_ttl_market_open_seconds = 300
        ai_cache_ttl_market_closed_seconds = 21600
        global_news_cache_ttl_market_open_seconds = 300
        global_news_cache_ttl_market_closed_seconds = 21600
        global_news_poll_market_open_seconds = 300
        global_news_poll_market_closed_seconds = 3600

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


def is_trading_day(day: date) -> bool:
    return day.weekday() in MARKET_WEEKDAYS


def current_trading_date(now_utc: datetime | None = None) -> date:
    return to_ist(now_utc).date()


def previous_trading_day(day: date) -> date:
    current = day - timedelta(days=1)
    while not is_trading_day(current):
        current -= timedelta(days=1)
    return current


def latest_completed_trading_day(now_utc: datetime | None = None) -> date:
    now_ist = to_ist(now_utc)
    if is_trading_day(now_ist.date()) and now_ist.time() > MARKET_CLOSE:
        return now_ist.date()
    return previous_trading_day(now_ist.date())


def trading_date_for_timestamp(ts: datetime | None) -> date | None:
    if ts is None:
        return None
    return to_ist(ts).date()


def trading_day_close_utc(day: date) -> datetime:
    close_ist = datetime.combine(day, MARKET_CLOSE, tzinfo=timezone(IST_OFFSET))
    return close_ist.astimezone(timezone.utc)


def needs_completed_day_refresh(
    latest_ts: datetime | None,
    now_utc: datetime | None = None,
    *,
    tolerance_minutes: int = 20,
) -> bool:
    if latest_ts is None:
        return True
    expected_close = trading_day_close_utc(latest_completed_trading_day(now_utc))
    return latest_ts < (expected_close - timedelta(minutes=tolerance_minutes))


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


def global_news_cache_ttl_seconds(now_utc: datetime | None = None) -> int:
    if is_indian_market_open(now_utc):
        return settings.global_news_cache_ttl_market_open_seconds
    return settings.global_news_cache_ttl_market_closed_seconds


def global_news_poll_interval_seconds(now_utc: datetime | None = None) -> int:
    if is_indian_market_open(now_utc):
        return settings.global_news_poll_market_open_seconds
    return settings.global_news_poll_market_closed_seconds


def should_refresh_intraday_caches(now_utc: datetime | None = None) -> bool:
    return is_indian_market_open(now_utc)
