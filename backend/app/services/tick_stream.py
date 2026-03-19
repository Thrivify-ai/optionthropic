"""
Pro Tick Stream — live tick data for NIFTY, BANKNIFTY, SENSEX.

Connects to Zerodha WebSocket (KiteTicker) when configured.
Stores latest ticks in memory. Falls back to DB/quote polling when unavailable.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# Symbol mapping: our name -> Kite exchange:tradingsymbol
_INDEX_KEYS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "SENSEX": "BSE:SENSEX",
}

# In-memory tick store: { symbol: { price, change, timestamp } }
_tick_store: dict[str, dict[str, Any]] = {}
# Rolling 30-second price history for 10s momentum: { symbol: deque of (ts, price) }
_tick_history: dict[str, deque] = {}
_history_lock = threading.Lock()

# Previous day close (or today's open) — reference for change calculation
_ref_price: dict[str, float] = {}
_kite_ticker_thread: threading.Thread | None = None
_ws_connected = False


# Token -> symbol mapping (populated on connect)
_TOKEN_TO_SYM: dict[int, str] = {}


def _get_tokens() -> dict[str, int]:
    """Resolve instrument tokens for NIFTY, BANKNIFTY, SENSEX."""
    global _TOKEN_TO_SYM
    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return {}
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.zerodha_api_key)
        kite.set_access_token(settings.zerodha_access_token)
        result = {}
        for i in kite.instruments("NSE") + kite.instruments("BSE"):
            ts = i.get("tradingsymbol", "")
            tok = i.get("instrument_token")
            if not tok:
                continue
            if ts == "NIFTY 50":
                result["NIFTY"] = tok
                _TOKEN_TO_SYM[tok] = "NIFTY"
            elif ts == "NIFTY BANK":
                result["BANKNIFTY"] = tok
                _TOKEN_TO_SYM[tok] = "BANKNIFTY"
            elif ts == "SENSEX":
                result["SENSEX"] = tok
                _TOKEN_TO_SYM[tok] = "SENSEX"
        return result
    except Exception as e:
        logger.warning("tick_stream_token_resolve_failed", error=str(e))
        return {}


def _refresh_ref_prices():
    """Fetch previous close from quote API to use as change baseline."""
    global _ref_price
    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.zerodha_api_key)
        kite.set_access_token(settings.zerodha_access_token)
        q = kite.quote(list(_INDEX_KEYS.values()))
        for key, data in q.items():
            sym = next((s for s, k in _INDEX_KEYS.items() if k == key), None)
            if not sym:
                continue
            ohlc = data.get("ohlc") or {}
            # Prefer previous close (ohlc.close = prior day close for indices)
            ref = ohlc.get("close") or ohlc.get("open")
            if ref is not None:
                _ref_price[sym] = float(ref)
    except Exception as e:
        logger.debug("tick_stream_refresh_ref_prices_failed", error=str(e))


def _on_ticks(ws, ticks):
    """KiteTicker callback: process incoming ticks."""
    global _tick_store, _ref_price, _tick_history

    for t in ticks:
        sym = _TOKEN_TO_SYM.get(t.get("instrument_token"))
        if not sym:
            continue
        ltp = t.get("last_price") or t.get("last_traded_price", 0)
        if not ltp:
            continue
        ltp_f = float(ltp)

        # Change from previous close (not tick-to-tick)
        ref = _ref_price.get(sym)
        if ref is None:
            ohlc = t.get("ohlc") or {}
            ref = ohlc.get("close") or ohlc.get("open")
            if ref is not None:
                _ref_price[sym] = float(ref)
        change = round(ltp_f - ref, 2) if ref is not None else 0

        with _history_lock:
            if sym not in _tick_history:
                _tick_history[sym] = deque(maxlen=120)
            _tick_history[sym].append((time.time(), ltp_f))

        _tick_store[sym] = {
            "price": round(ltp_f, 2),
            "change": change,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def _on_connect(ws, response):
    global _ws_connected
    _ws_connected = True
    logger.info("Pro tick stream WebSocket connected")
    _refresh_ref_prices()
    tokens = list(_get_tokens().values())
    if tokens:
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_QUOTE, tokens)


def _on_close(ws, code, reason):
    global _ws_connected
    _ws_connected = False
    logger.info("Pro tick stream WebSocket closed", code=code, reason=reason)


def _run_kite_ticker():
    """Run KiteTicker in a blocking loop (runs in thread)."""
    global _kite_ticker_thread
    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return
    tokens = _get_tokens()
    if not tokens:
        logger.warning("Pro tick stream: no instrument tokens found")
        return
    try:
        from kiteconnect import KiteTicker
        kws = KiteTicker(settings.zerodha_api_key, settings.zerodha_access_token)
        kws.on_ticks = _on_ticks
        kws.on_connect = _on_connect
        kws.on_close = _on_close
        kws.connect(threaded=False)
    except Exception as e:
        logger.warning("Pro tick stream KiteTicker failed", error=str(e))
    finally:
        _kite_ticker_thread = None


def start_tick_stream():
    """Start the tick stream WebSocket in a background thread."""
    global _kite_ticker_thread
    if _kite_ticker_thread and _kite_ticker_thread.is_alive():
        return
    _kite_ticker_thread = threading.Thread(target=_run_kite_ticker, daemon=True)
    _kite_ticker_thread.start()
    logger.info("Pro tick stream thread started")


def get_latest_ticks() -> dict[str, dict[str, Any]]:
    """Return latest ticks for all indices. Change = current - previous close."""
    if _tick_store:
        return dict(_tick_store)

    # No WebSocket data — try kite.quote() immediately (faster than waiting for ticks)
    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return {}
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.zerodha_api_key)
        kite.set_access_token(settings.zerodha_access_token)
        keys = list(_INDEX_KEYS.values())
        q = kite.quote(keys)
        _refresh_ref_prices()
        out = {}
        sym_map = {v: k for k, v in _INDEX_KEYS.items()}
        for key, data in q.items():
            sym = sym_map.get(key)
            if not sym:
                continue
            ltp = data.get("last_price") or data.get("ohlc", {}).get("close", 0)
            ohlc = data.get("ohlc") or {}
            ref = ohlc.get("close") or ohlc.get("open")
            change = round(float(ltp) - ref, 2) if ref is not None else 0
            out[sym] = {
                "price": round(float(ltp), 2),
                "change": change,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return out
    except Exception as e:
        logger.debug("Pro tick fallback quote failed", error=str(e))
        return {}


def get_price_10s_ago(symbol: str) -> float | None:
    """Return price from ~10 seconds ago for momentum calculation."""
    with _history_lock:
        hist = _tick_history.get(symbol)
        if not hist or len(hist) < 2:
            return None
        now = time.time()
        target = now - 10
        best = None
        best_diff = float("inf")
        for ts, price in hist:
            d = abs(ts - target)
            if d < best_diff and ts <= now:
                best_diff = d
                best = price
        return best
