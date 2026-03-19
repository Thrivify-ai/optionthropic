"""
Index Quotes — fetch NIFTY, BANKNIFTY, SENSEX price + yesterday's close from Zerodha.

Used when DB has no pre-market snapshots (fresh start or insufficient history).
Zerodha Kite quote API returns ohlc.close = previous trading day's close.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_INDEX_KEYS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "SENSEX": "BSE:SENSEX",
}

# Cache for 10 minutes to avoid repeated Zerodha calls
_cache: dict[str, Any] | None = None
_cache_ts: float = 0
_CACHE_TTL_SEC = 600


async def fetch_index_quotes_from_zerodha() -> dict[str, dict[str, Any]]:
    """
    Fetch current price and previous close for NIFTY, BANKNIFTY, SENSEX from Zerodha.

    Returns: { "NIFTY": { "price": 24500, "prev_close": 24400, "change": 100, "change_pct": 0.41 }, ... }
    """
    global _cache, _cache_ts
    now = datetime.now(timezone.utc).timestamp()
    if _cache is not None and (now - _cache_ts) < _CACHE_TTL_SEC:
        return _cache

    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return {}

    try:
        from kiteconnect import KiteConnect  # type: ignore[import]

        kite = KiteConnect(api_key=settings.zerodha_api_key)
        kite.set_access_token(settings.zerodha_access_token)
        keys = list(_INDEX_KEYS.values())

        loop = asyncio.get_event_loop()
        quotes = await loop.run_in_executor(None, lambda: kite.quote(keys))

        result: dict[str, dict[str, Any]] = {}
        for symbol, kite_key in _INDEX_KEYS.items():
            q = quotes.get(kite_key, {}) or {}
            last = q.get("last_price")
            ohlc = q.get("ohlc", {}) or {}
            prev_close = ohlc.get("close")  # previous trading day close

            price = float(last) if last is not None else None
            base = float(prev_close) if prev_close is not None else None

            change = round(price - base, 2) if (price is not None and base) else None
            change_pct = round(change / base * 100, 2) if (change is not None and base) else None

            result[symbol] = {
                "price": price,
                "prev_close": base,
                "change": change,
                "change_pct": change_pct,
            }
        logger.info("Fetched index quotes from Zerodha", symbols=list(result.keys()))
        _cache = result
        _cache_ts = now
        return result
    except Exception as exc:
        logger.warning("Zerodha index quote fetch failed", error=str(exc))
        return {}
