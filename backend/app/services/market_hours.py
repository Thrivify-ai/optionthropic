"""
Market-hours helpers for Indian index trading.
"""

from __future__ import annotations

from dataclasses import dataclass
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
MCX_DAY_OPEN = dtime(9, 0)
MCX_DAY_CLOSE = dtime(17, 0)
MCX_EVENING_OPEN = dtime(17, 0)
MCX_EVENING_CLOSE = dtime(23, 30)

_EQUITY_HOLIDAYS: dict[date, str] = {
    date(2026, 1, 26): "Republic Day",
    date(2026, 2, 19): "Chatrapati Shivaji Maharaj Jayanti",
    date(2026, 3, 3): "Holi",
    date(2026, 3, 19): "Gudi Padwa",
    date(2026, 3, 26): "Shri Ram Navami",
    date(2026, 3, 31): "Shri Mahavir Jayanti",
    date(2026, 4, 1): "Annual Bank Closing",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day / Buddha Pournima",
    date(2026, 5, 28): "Bakri Id",
    date(2026, 6, 26): "Muharram",
    date(2026, 8, 26): "Id-E-Milad",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 10): "Diwali-Balipratipada",
    date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2026, 12, 25): "Christmas",
}

# MCX has separate day and evening sessions. On many Indian holidays the day
# session is closed while the evening session reopens. This table keeps the
# tracker and collector honest instead of pretending the whole market is open.
_MCX_HOLIDAY_SESSIONS: dict[date, tuple[bool, bool, str]] = {
    date(2026, 1, 1): (False, False, "New Year Day"),
    date(2026, 1, 26): (False, True, "Republic Day"),
    date(2026, 3, 3): (False, True, "Holi"),
    date(2026, 3, 26): (False, True, "Shri Ram Navami"),
    date(2026, 3, 31): (False, True, "Shri Mahavir Jayanti"),
    date(2026, 4, 3): (False, False, "Good Friday"),
    date(2026, 4, 14): (False, True, "Dr. Baba Saheb Ambedkar Jayanti"),
    date(2026, 5, 1): (False, True, "Maharashtra Day / Buddha Pournima"),
    date(2026, 5, 28): (False, True, "Bakri Id"),
    date(2026, 6, 26): (False, True, "Muharram"),
    date(2026, 9, 14): (False, True, "Ganesh Chaturthi"),
    date(2026, 10, 2): (False, False, "Mahatma Gandhi Jayanti"),
    date(2026, 10, 20): (False, True, "Dussehra"),
    date(2026, 11, 10): (False, True, "Diwali-Balipratipada"),
    date(2026, 11, 24): (False, True, "Prakash Gurpurb Sri Guru Nanak Dev"),
    date(2026, 12, 25): (False, False, "Christmas"),
}


@dataclass(frozen=True)
class ExchangeStatus:
    exchange: str
    is_open: bool
    session: str
    is_holiday: bool
    reason: str
    next_open_ist: str | None = None


def to_ist(now_utc: datetime | None = None) -> datetime:
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone(IST_OFFSET))


def holiday_name(day: date) -> str | None:
    return _EQUITY_HOLIDAYS.get(day)


def is_trading_day(day: date) -> bool:
    return day.weekday() in MARKET_WEEKDAYS and day not in _EQUITY_HOLIDAYS


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
    return is_trading_day(now_ist.date()) and MARKET_OPEN <= now_ist.time() <= MARKET_CLOSE


def _format_next_open(day: date, at: dtime) -> str:
    return f"{day.isoformat()} {at.strftime('%H:%M')} IST"


def _next_equity_open_day(day: date) -> date:
    current = day
    while current.weekday() not in MARKET_WEEKDAYS or current in _EQUITY_HOLIDAYS:
        current += timedelta(days=1)
    return current


def get_equity_market_status(now_utc: datetime | None = None) -> ExchangeStatus:
    now_ist = to_ist(now_utc)
    current_day = now_ist.date()
    if current_day in _EQUITY_HOLIDAYS:
        next_day = _next_equity_open_day(current_day + timedelta(days=1))
        return ExchangeStatus(
            exchange="EQUITIES",
            is_open=False,
            session="CLOSED",
            is_holiday=True,
            reason=f"Holiday: {_EQUITY_HOLIDAYS[current_day]}",
            next_open_ist=_format_next_open(next_day, MARKET_OPEN),
        )
    if current_day.weekday() not in MARKET_WEEKDAYS:
        next_day = _next_equity_open_day(current_day + timedelta(days=1))
        return ExchangeStatus(
            exchange="EQUITIES",
            is_open=False,
            session="CLOSED",
            is_holiday=False,
            reason="Weekend",
            next_open_ist=_format_next_open(next_day, MARKET_OPEN),
        )
    if MARKET_OPEN <= now_ist.time() <= MARKET_CLOSE:
        return ExchangeStatus(
            exchange="EQUITIES",
            is_open=True,
            session="REGULAR",
            is_holiday=False,
            reason="Regular trading session",
        )
    if now_ist.time() < MARKET_OPEN:
        return ExchangeStatus(
            exchange="EQUITIES",
            is_open=False,
            session="PREOPEN",
            is_holiday=False,
            reason="Pre-open waiting for the cash session",
            next_open_ist=_format_next_open(current_day, MARKET_OPEN),
        )
    next_day = _next_equity_open_day(current_day + timedelta(days=1))
    return ExchangeStatus(
        exchange="EQUITIES",
        is_open=False,
        session="POSTCLOSE",
        is_holiday=False,
        reason="Cash session closed for the day",
        next_open_ist=_format_next_open(next_day, MARKET_OPEN),
    )


def get_mcx_market_status(now_utc: datetime | None = None) -> ExchangeStatus:
    now_ist = to_ist(now_utc)
    current_day = now_ist.date()
    holiday_rule = _MCX_HOLIDAY_SESSIONS.get(current_day)

    if current_day.weekday() not in MARKET_WEEKDAYS:
        next_day = current_day + timedelta(days=1)
        while next_day.weekday() not in MARKET_WEEKDAYS:
            next_day += timedelta(days=1)
        return ExchangeStatus(
            exchange="MCX",
            is_open=False,
            session="CLOSED",
            is_holiday=False,
            reason="Weekend",
            next_open_ist=_format_next_open(next_day, MCX_DAY_OPEN),
        )

    if holiday_rule is not None:
        day_open, evening_open, name = holiday_rule
        if MCX_DAY_OPEN <= now_ist.time() < MCX_DAY_CLOSE:
            return ExchangeStatus(
                exchange="MCX",
                is_open=day_open,
                session="DAY",
                is_holiday=True,
                reason=f"Holiday day session: {name}",
                next_open_ist=_format_next_open(current_day, MCX_EVENING_OPEN) if evening_open else None,
            )
        if MCX_EVENING_OPEN <= now_ist.time() <= MCX_EVENING_CLOSE:
            return ExchangeStatus(
                exchange="MCX",
                is_open=evening_open,
                session="EVENING",
                is_holiday=True,
                reason=(f"Holiday evening session open: {name}" if evening_open else f"Holiday: {name}"),
            )
        if now_ist.time() < MCX_DAY_OPEN:
            return ExchangeStatus(
                exchange="MCX",
                is_open=False,
                session="PREOPEN",
                is_holiday=True,
                reason=f"Holiday morning session closed: {name}",
                next_open_ist=_format_next_open(current_day, MCX_EVENING_OPEN) if evening_open else None,
            )
        next_day = current_day + timedelta(days=1)
        while next_day.weekday() not in MARKET_WEEKDAYS:
            next_day += timedelta(days=1)
        return ExchangeStatus(
            exchange="MCX",
            is_open=False,
            session="POSTCLOSE",
            is_holiday=True,
            reason=f"Holiday schedule completed: {name}",
            next_open_ist=_format_next_open(next_day, MCX_DAY_OPEN),
        )

    if MCX_DAY_OPEN <= now_ist.time() < MCX_DAY_CLOSE:
        return ExchangeStatus(
            exchange="MCX",
            is_open=True,
            session="DAY",
            is_holiday=False,
            reason="Regular day session",
        )
    if MCX_EVENING_OPEN <= now_ist.time() <= MCX_EVENING_CLOSE:
        return ExchangeStatus(
            exchange="MCX",
            is_open=True,
            session="EVENING",
            is_holiday=False,
            reason="Regular evening session",
        )
    if now_ist.time() < MCX_DAY_OPEN:
        return ExchangeStatus(
            exchange="MCX",
            is_open=False,
            session="PREOPEN",
            is_holiday=False,
            reason="Waiting for the day session",
            next_open_ist=_format_next_open(current_day, MCX_DAY_OPEN),
        )
    return ExchangeStatus(
        exchange="MCX",
        is_open=False,
        session="INTERMISSION",
        is_holiday=False,
        reason="Waiting for the evening session",
        next_open_ist=_format_next_open(current_day, MCX_EVENING_OPEN),
    )


def is_mcx_market_open(now_utc: datetime | None = None) -> bool:
    return get_mcx_market_status(now_utc).is_open


def is_market_news_window_open(now_utc: datetime | None = None) -> bool:
    """News risk matters while either equities or MCX is actively trading."""
    return is_indian_market_open(now_utc) or is_mcx_market_open(now_utc)


def dashboard_cache_ttl_seconds(now_utc: datetime | None = None) -> int:
    if is_indian_market_open(now_utc):
        return settings.dashboard_cache_ttl_market_open_seconds
    return settings.dashboard_cache_ttl_market_closed_seconds


def ai_cache_ttl_seconds(now_utc: datetime | None = None) -> int:
    if is_indian_market_open(now_utc):
        return settings.ai_cache_ttl_market_open_seconds
    return settings.ai_cache_ttl_market_closed_seconds


def global_news_cache_ttl_seconds(now_utc: datetime | None = None) -> int:
    if is_market_news_window_open(now_utc):
        return settings.global_news_cache_ttl_market_open_seconds
    return settings.global_news_cache_ttl_market_closed_seconds


def global_news_poll_interval_seconds(now_utc: datetime | None = None) -> int:
    if is_market_news_window_open(now_utc):
        return settings.global_news_poll_market_open_seconds
    return settings.global_news_poll_market_closed_seconds


def should_refresh_intraday_caches(now_utc: datetime | None = None) -> bool:
    return is_indian_market_open(now_utc)
