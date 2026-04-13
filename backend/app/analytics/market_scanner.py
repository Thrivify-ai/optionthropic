"""
Breadth and leadership scanners built from Zerodha quotes.

Zerodha does not expose a scanner API, so we build lightweight universes from
quotes and keep the result cached. These snapshots are used both for signal
filtering and for future scanner-facing APIs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from app.logging_config import get_logger

    logger = get_logger(__name__)
except Exception:
    logger = logging.getLogger(__name__)

_SCANNER_CACHE_TTL_SECONDS = 30

_UNIVERSES: dict[str, list[tuple[str, float]]] = {
    "NIFTY": [
        ("NSE:RELIANCE", 1.00),
        ("NSE:HDFCBANK", 0.95),
        ("NSE:ICICIBANK", 0.85),
        ("NSE:INFY", 0.80),
        ("NSE:TCS", 0.78),
        ("NSE:BHARTIARTL", 0.62),
        ("NSE:ITC", 0.60),
        ("NSE:LT", 0.58),
        ("NSE:SBIN", 0.55),
        ("NSE:AXISBANK", 0.44),
        ("NSE:KOTAKBANK", 0.42),
        ("NSE:HINDUNILVR", 0.40),
    ],
    "BANKNIFTY": [
        ("NSE:HDFCBANK", 1.00),
        ("NSE:ICICIBANK", 0.95),
        ("NSE:SBIN", 0.90),
        ("NSE:AXISBANK", 0.75),
        ("NSE:KOTAKBANK", 0.72),
        ("NSE:INDUSINDBK", 0.56),
        ("NSE:BANKBARODA", 0.52),
        ("NSE:PNB", 0.50),
        ("NSE:AUBANK", 0.36),
        ("NSE:IDFCFIRSTB", 0.34),
        ("NSE:FEDERALBNK", 0.30),
        ("NSE:CANBK", 0.28),
    ],
    "SENSEX": [
        ("NSE:RELIANCE", 1.00),
        ("NSE:HDFCBANK", 0.94),
        ("NSE:ICICIBANK", 0.85),
        ("NSE:INFY", 0.82),
        ("NSE:TCS", 0.80),
        ("NSE:LT", 0.60),
        ("NSE:SBIN", 0.55),
        ("NSE:ITC", 0.52),
        ("NSE:HINDUNILVR", 0.48),
        ("NSE:BHARTIARTL", 0.44),
    ],
}


@dataclass(frozen=True)
class MarketBreadthSnapshot:
    symbol: str
    universe_size: int
    advancers: int
    decliners: int
    unchanged: int
    avg_change_pct: float
    breadth_score: int
    leadership_score: int
    direction_bias: str
    aligned_bullish: bool
    aligned_bearish: bool
    available: bool
    reason: str
    fetched_at: str


def _cache_key(symbol: str) -> str:
    return f"market-scanner:breadth:{symbol.upper()}:v1"


def _change_pct_for_quote(payload: dict[str, Any]) -> float | None:
    last_price = payload.get("last_price")
    ohlc = payload.get("ohlc") or {}
    prev_close = ohlc.get("close") or ohlc.get("open")
    if last_price in (None, 0) or prev_close in (None, 0):
        return None
    try:
        return round((float(last_price) - float(prev_close)) / float(prev_close) * 100.0, 3)
    except Exception:
        return None


def summarize_market_breadth(
    symbol: str,
    quotes: dict[str, dict[str, Any]],
) -> MarketBreadthSnapshot:
    universe = _UNIVERSES.get(symbol.upper(), [])
    if not universe:
        return MarketBreadthSnapshot(
            symbol=symbol.upper(),
            universe_size=0,
            advancers=0,
            decliners=0,
            unchanged=0,
            avg_change_pct=0.0,
            breadth_score=0,
            leadership_score=0,
            direction_bias="neutral",
            aligned_bullish=False,
            aligned_bearish=False,
            available=False,
            reason="No breadth universe configured.",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    advancers = decliners = unchanged = 0
    weighted_change = 0.0
    total_weight = 0.0
    up_weight = 0.0
    down_weight = 0.0

    for instrument_key, weight in universe:
        quote = quotes.get(instrument_key) or {}
        change_pct = _change_pct_for_quote(quote)
        if change_pct is None:
            continue

        total_weight += weight
        weighted_change += change_pct * weight
        if change_pct > 0.05:
            advancers += 1
            up_weight += weight
        elif change_pct < -0.05:
            decliners += 1
            down_weight += weight
        else:
            unchanged += 1

    total = advancers + decliners + unchanged
    if total == 0 or total_weight <= 0:
        return MarketBreadthSnapshot(
            symbol=symbol.upper(),
            universe_size=0,
            advancers=0,
            decliners=0,
            unchanged=0,
            avg_change_pct=0.0,
            breadth_score=0,
            leadership_score=0,
            direction_bias="neutral",
            aligned_bullish=False,
            aligned_bearish=False,
            available=False,
            reason="Breadth quotes are unavailable right now.",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    avg_change_pct = round(weighted_change / total_weight, 3)
    breadth_edge = ((advancers - decliners) / total) * 55.0
    leadership_edge = ((up_weight - down_weight) / total_weight) * 45.0
    leadership_score = int(round(max(-100.0, min(100.0, leadership_edge))))
    breadth_score = int(round(max(-100.0, min(100.0, breadth_edge + avg_change_pct * 14.0 + leadership_edge))))

    if breadth_score >= 18:
        direction_bias = "bullish"
    elif breadth_score <= -18:
        direction_bias = "bearish"
    else:
        direction_bias = "neutral"

    reason = (
        f"{advancers}/{total} advancers, {decliners}/{total} decliners, "
        f"avg change {avg_change_pct:+.2f}%, leadership {leadership_score:+d}."
    )
    return MarketBreadthSnapshot(
        symbol=symbol.upper(),
        universe_size=total,
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        avg_change_pct=avg_change_pct,
        breadth_score=breadth_score,
        leadership_score=leadership_score,
        direction_bias=direction_bias,
        aligned_bullish=direction_bias == "bullish",
        aligned_bearish=direction_bias == "bearish",
        available=True,
        reason=reason,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


async def fetch_market_breadth_snapshot(
    symbol: str,
    *,
    force_refresh: bool = False,
) -> MarketBreadthSnapshot:
    from app.config import settings
    from app.services.runtime_cache import runtime_cache

    symbol_key = symbol.upper()
    if symbol_key not in _UNIVERSES:
        return summarize_market_breadth(symbol_key, {})

    if not force_refresh:
        cached = await runtime_cache.get_json(_cache_key(symbol_key))
        if isinstance(cached, dict):
            try:
                return MarketBreadthSnapshot(**cached)
            except TypeError:
                pass

    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        snapshot = summarize_market_breadth(symbol_key, {})
        await runtime_cache.set_json(_cache_key(symbol_key), asdict(snapshot), ttl_seconds=_SCANNER_CACHE_TTL_SECONDS)
        return snapshot

    try:
        from kiteconnect import KiteConnect

        loop = asyncio.get_running_loop()
        instruments = [item[0] for item in _UNIVERSES[symbol_key]]

        def _quote() -> dict[str, dict[str, Any]]:
            kite = KiteConnect(api_key=settings.zerodha_api_key)
            kite.set_access_token(settings.zerodha_access_token)
            return kite.quote(instruments)

        quotes = await loop.run_in_executor(None, _quote)
        snapshot = summarize_market_breadth(symbol_key, quotes)
    except Exception as exc:
        logger.debug("market_breadth_fetch_failed symbol=%s error=%s", symbol_key, str(exc))
        snapshot = summarize_market_breadth(symbol_key, {})

    await runtime_cache.set_json(_cache_key(symbol_key), asdict(snapshot), ttl_seconds=_SCANNER_CACHE_TTL_SECONDS)
    return snapshot
