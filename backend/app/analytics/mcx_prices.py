"""
MCX Prices — lightweight commodities ticker.

Uses Zerodha Kite Connect (same API key / access token already configured)
to fetch the nearest-future contract price for:
  - CRUDEOIL
  - NATGAS
  - GOLD
  - SILVER

No database writes. Designed for fast UI display.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Optional

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# Cache instruments per day (in-process)
_cache_date: Optional[str] = None
_cache_instruments: list[dict[str, Any]] = []


def _get_kite() -> Any:
    from kiteconnect import KiteConnect  # type: ignore[import]

    kite = KiteConnect(api_key=settings.zerodha_api_key)
    kite.set_access_token(settings.zerodha_access_token)
    return kite


async def _get_mcx_instruments(loop) -> list[dict[str, Any]]:
    global _cache_date, _cache_instruments
    today = str(date.today())
    if _cache_date == today and _cache_instruments:
        return _cache_instruments

    kite = _get_kite()
    logger.info("Fetching Zerodha instruments", exchange="MCX")
    instruments = await loop.run_in_executor(None, lambda: kite.instruments("MCX"))
    _cache_date = today
    _cache_instruments = instruments
    return instruments


def _pick_nearest_future(instruments: list[dict[str, Any]], name: str) -> Optional[dict[str, Any]]:
    """
    Pick nearest-expiry FUT for commodity name (e.g. CRUDEOIL, NATGAS).
    Zerodha MCX instruments: segment=MCX, instrument_type=FUT.
    """
    futs = [
        i
        for i in instruments
        if (i.get("name") == name or i.get("tradingsymbol", "").upper().startswith(name))
        and i.get("instrument_type") == "FUT"
        and i.get("expiry") is not None
    ]
    if not futs:
        return None
    futs.sort(key=lambda x: x["expiry"])
    return futs[0]


async def get_mcx_prices() -> dict[str, Any]:
    """
    Returns:
      {
        "CRUDEOIL": {"price": .., "change": .., "change_pct": .., "symbol": "MCX:..."},
        "NATGAS":   {...}
      }
    """
    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return {"error": "Zerodha credentials not configured"}

    loop = asyncio.get_event_loop()
    logger.info("MCX prices request")
    instruments = await _get_mcx_instruments(loop)

    picks = {}
    for name in ("CRUDEOIL", "NATGAS", "GOLD", "SILVER"):
        inst = _pick_nearest_future(instruments, name)
        if inst:
            picks[name] = f"MCX:{inst['tradingsymbol']}"

    if not picks:
        return {"error": "No MCX futures instruments found"}

    kite = _get_kite()
    try:
        quotes = await loop.run_in_executor(None, lambda: kite.quote(list(picks.values())))
    except Exception as exc:
        logger.warning("MCX quote failed", error=str(exc), picks=list(picks.values()))
        return {"error": f"MCX quote failed: {exc}"}

    out: dict[str, Any] = {}
    for name, key in picks.items():
        q = quotes.get(key, {}) or {}
        last = q.get("last_price")
        ohlc = q.get("ohlc", {}) or {}
        close = ohlc.get("close")  # previous close provided by Kite
        price = float(last) if last is not None else None
        base = float(close) if close is not None else None
        change = round(price - base, 2) if (price is not None and base) else None
        change_pct = round(change / base * 100, 2) if (change is not None and base) else None
        out[name] = {
            "symbol": key,
            "price": price,
            "change": change,
            "change_pct": change_pct,
        }
    return out

