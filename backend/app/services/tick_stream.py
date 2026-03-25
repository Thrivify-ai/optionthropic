"""
Pro tick stream for NIFTY, BANKNIFTY, and SENSEX.

The service prefers the Zerodha WebSocket when available. When it is not,
it keeps a lightweight quote poller running so quick-signal v3 still has
fast-enough price history to reason about 10s-60s momentum.
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

_INDEX_KEYS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "SENSEX": "BSE:SENSEX",
}

_tick_store: dict[str, dict[str, Any]] = {}
_tick_history: dict[str, deque[tuple[float, float]]] = {}
_history_lock = threading.Lock()

_ref_price: dict[str, float] = {}
_kite_ticker_client: Any | None = None
_ws_connected = False
_quote_poller_thread: threading.Thread | None = None
_quote_poller_stop = threading.Event()
_TOKEN_TO_SYM: dict[int, str] = {}
_HISTORY_MAXLEN = 720


def _get_tokens() -> dict[str, int]:
    global _TOKEN_TO_SYM

    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return {}

    try:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=settings.zerodha_api_key)
        kite.set_access_token(settings.zerodha_access_token)
        result: dict[str, int] = {}

        for instrument in kite.instruments("NSE") + kite.instruments("BSE"):
            tradingsymbol = instrument.get("tradingsymbol", "")
            token = instrument.get("instrument_token")
            if not token:
                continue
            if tradingsymbol == "NIFTY 50":
                result["NIFTY"] = token
                _TOKEN_TO_SYM[token] = "NIFTY"
            elif tradingsymbol == "NIFTY BANK":
                result["BANKNIFTY"] = token
                _TOKEN_TO_SYM[token] = "BANKNIFTY"
            elif tradingsymbol == "SENSEX":
                result["SENSEX"] = token
                _TOKEN_TO_SYM[token] = "SENSEX"
        return result
    except Exception as exc:
        logger.warning("tick_stream_token_resolve_failed", error=str(exc))
        return {}


def _refresh_ref_prices() -> None:
    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return

    try:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=settings.zerodha_api_key)
        kite.set_access_token(settings.zerodha_access_token)
        quotes = kite.quote(list(_INDEX_KEYS.values()))
        for key, data in quotes.items():
            symbol = next((sym for sym, lookup in _INDEX_KEYS.items() if lookup == key), None)
            if not symbol:
                continue
            ohlc = data.get("ohlc") or {}
            ref = ohlc.get("close") or ohlc.get("open")
            if ref is not None:
                _ref_price[symbol] = float(ref)
    except Exception as exc:
        logger.debug("tick_stream_refresh_ref_prices_failed", error=str(exc))


def _record_price_point(
    symbol: str,
    *,
    price: float,
    change: float,
    timestamp_iso: str | None = None,
    epoch_seconds: float | None = None,
) -> None:
    ts_epoch = float(epoch_seconds or time.time())
    ts_iso = timestamp_iso or datetime.now(timezone.utc).isoformat()
    price = round(float(price), 2)
    change = round(float(change), 2)

    with _history_lock:
        history = _tick_history.setdefault(symbol, deque(maxlen=_HISTORY_MAXLEN))
        if not history or abs(history[-1][0] - ts_epoch) >= 0.5 or history[-1][1] != price:
            history.append((ts_epoch, price))

    _tick_store[symbol] = {
        "price": price,
        "change": change,
        "timestamp": ts_iso,
    }


def _fetch_quote_snapshot() -> dict[str, dict[str, Any]]:
    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return {}

    try:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=settings.zerodha_api_key)
        kite.set_access_token(settings.zerodha_access_token)
        quotes = kite.quote(list(_INDEX_KEYS.values()))
        _refresh_ref_prices()

        output: dict[str, dict[str, Any]] = {}
        reverse_map = {lookup: symbol for symbol, lookup in _INDEX_KEYS.items()}
        now_iso = datetime.now(timezone.utc).isoformat()
        now_epoch = time.time()

        for key, data in quotes.items():
            symbol = reverse_map.get(key)
            if not symbol:
                continue
            last_price = data.get("last_price") or data.get("ohlc", {}).get("close")
            if last_price is None:
                continue
            ref = _ref_price.get(symbol)
            if ref is None:
                ohlc = data.get("ohlc") or {}
                ref = ohlc.get("close") or ohlc.get("open")
                if ref is not None:
                    _ref_price[symbol] = float(ref)
            change = round(float(last_price) - float(ref), 2) if ref is not None else 0.0
            _record_price_point(
                symbol,
                price=float(last_price),
                change=change,
                timestamp_iso=now_iso,
                epoch_seconds=now_epoch,
            )
            output[symbol] = dict(_tick_store[symbol])

        return output
    except Exception as exc:
        logger.debug("Pro tick fallback quote failed", error=str(exc))
        return {}


def _quote_poller_loop() -> None:
    interval = max(2, int(settings.fast_tick_poll_seconds or 5))
    while not _quote_poller_stop.is_set():
        if not _ws_connected:
            _fetch_quote_snapshot()
        _quote_poller_stop.wait(interval)


def _on_ticks(ws, ticks) -> None:
    global _ref_price

    for tick in ticks:
        symbol = _TOKEN_TO_SYM.get(tick.get("instrument_token"))
        if not symbol:
            continue

        last_price = tick.get("last_price") or tick.get("last_traded_price")
        if not last_price:
            continue

        ref = _ref_price.get(symbol)
        if ref is None:
            ohlc = tick.get("ohlc") or {}
            ref = ohlc.get("close") or ohlc.get("open")
            if ref is not None:
                _ref_price[symbol] = float(ref)
        change = round(float(last_price) - float(ref), 2) if ref is not None else 0.0
        _record_price_point(
            symbol,
            price=float(last_price),
            change=change,
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            epoch_seconds=time.time(),
        )


def _on_connect(ws, response) -> None:
    global _ws_connected
    _ws_connected = True
    logger.info("Pro tick stream WebSocket connected")
    _refresh_ref_prices()
    tokens = list(_get_tokens().values())
    if tokens:
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_QUOTE, tokens)


def _on_close(ws, code, reason) -> None:
    global _kite_ticker_client, _ws_connected
    _ws_connected = False
    _kite_ticker_client = None
    logger.info("Pro tick stream WebSocket closed", code=code, reason=reason)


def start_tick_stream() -> None:
    global _kite_ticker_client, _quote_poller_thread

    if not settings.zerodha_api_key or not settings.zerodha_access_token:
        return

    if _quote_poller_thread is None or not _quote_poller_thread.is_alive():
        _quote_poller_stop.clear()
        _quote_poller_thread = threading.Thread(
            target=_quote_poller_loop,
            name="optionthropic-quote-poller",
            daemon=True,
        )
        _quote_poller_thread.start()
        logger.info(
            "Pro tick fallback quote poller started",
            interval_seconds=settings.fast_tick_poll_seconds,
        )

    if _kite_ticker_client is not None:
        return

    tokens = _get_tokens()
    if not tokens:
        logger.warning("Pro tick stream: no instrument tokens found")
        return

    try:
        from kiteconnect import KiteTicker

        ticker = KiteTicker(settings.zerodha_api_key, settings.zerodha_access_token)
        ticker.on_ticks = _on_ticks
        ticker.on_connect = _on_connect
        ticker.on_close = _on_close
        ticker.connect(threaded=True)
        _kite_ticker_client = ticker
        logger.info("Pro tick stream connection initiated")
    except Exception as exc:
        _kite_ticker_client = None
        logger.warning("Pro tick stream KiteTicker failed", error=str(exc))


def get_latest_ticks() -> dict[str, dict[str, Any]]:
    if _tick_store:
        return dict(_tick_store)
    return _fetch_quote_snapshot()


def get_latest_tick(symbol: str) -> dict[str, Any] | None:
    return get_latest_ticks().get(symbol.upper())


def get_price_10s_ago(symbol: str) -> float | None:
    return get_price_seconds_ago(symbol, 10)


def get_price_seconds_ago(
    symbol: str,
    seconds: int,
    *,
    tolerance_seconds: int | None = None,
) -> float | None:
    with _history_lock:
        history = _tick_history.get(symbol.upper())
        if not history or len(history) < 2:
            return None

        now_epoch = time.time()
        target = now_epoch - max(1, int(seconds))
        tolerance = tolerance_seconds if tolerance_seconds is not None else max(3, int(seconds * 0.6))
        best_price = None
        best_diff = float("inf")

        for ts_epoch, price in history:
            if ts_epoch > now_epoch:
                continue
            diff = abs(ts_epoch - target)
            if diff < best_diff:
                best_diff = diff
                best_price = price

        if best_price is None or best_diff > tolerance:
            return None
        return best_price


def get_tick_age_seconds(symbol: str) -> float | None:
    tick = _tick_store.get(symbol.upper())
    if not tick:
        return None

    ts_raw = tick.get("timestamp")
    if not ts_raw:
        return None

    try:
        ts = datetime.fromisoformat(ts_raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
