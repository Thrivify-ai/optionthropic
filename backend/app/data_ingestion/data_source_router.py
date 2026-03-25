"""
Routes data-fetching calls to the correct broker/exchange source
based on the DATA_SOURCE environment variable.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

import aiohttp
from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

# ─── Protocol ──────────────────────────────────────────────────────────────────


class DataSource(Protocol):
    async def fetch_option_chain(self, symbol: str) -> list[dict[str, Any]]:
        ...


# ─── NSE Source ────────────────────────────────────────────────────────────────

_NSE_SYMBOL_MAP = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "SENSEX": "SENSEX",
}

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}


class NSEDataSource:
    """Fetches option chain data directly from NSE public API."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._cookie_seeded: bool = False

    def _make_session(self) -> aiohttp.ClientSession:
        connector = aiohttp.TCPConnector(limit=10, ssl=False)
        return aiohttp.ClientSession(
            headers=_NSE_HEADERS,
            connector=connector,
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )

    async def _seed_cookies(self, session: aiohttp.ClientSession) -> None:
        """Visit NSE homepage and market-data page to acquire session cookies."""
        seed_urls = [
            settings.nse_api_url,
            f"{settings.nse_api_url}/market-data/live-equity-market",
        ]
        for url in seed_urls:
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=12),
                    allow_redirects=True,
                ) as resp:
                    await resp.read()
                    logger.debug("NSE cookie seed", url=url, status=resp.status)
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning("NSE cookie seed failed", url=url, error=str(exc))

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = self._make_session()
            self._cookie_seeded = False

        if not self._cookie_seeded:
            await self._seed_cookies(self._session)
            self._cookie_seeded = True

        return self._session

    async def fetch_option_chain(self, symbol: str) -> list[dict[str, Any]]:
        nse_symbol = _NSE_SYMBOL_MAP.get(symbol, symbol)
        url = f"{settings.nse_api_url}/api/option-chain-indices?symbol={nse_symbol}"

        for attempt in range(3):
            try:
                session = await self._get_session()
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 401 or resp.status == 403:
                        # Cookies expired — force re-seed on next attempt
                        self._cookie_seeded = False
                        await asyncio.sleep(2)
                        continue
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    records = _parse_nse_chain(data, symbol)
                    if records:
                        return records
                    # Empty parse — may be a non-JSON error page, re-seed
                    self._cookie_seeded = False
                    await asyncio.sleep(2)
            except Exception as exc:
                logger.warning(
                    "NSE fetch attempt failed",
                    symbol=symbol,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                self._cookie_seeded = False
                if self._session and not self._session.closed:
                    await self._session.close()
                self._session = None
                await asyncio.sleep(3)

        logger.error("NSE fetch exhausted retries", symbol=symbol)
        return []

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


def _parse_nse_chain(raw: dict, symbol: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        underlying = raw["records"]["underlyingValue"]
        source_timestamp = _parse_nse_source_timestamp(raw["records"].get("timestamp"))
        for entry in raw["records"]["data"]:
            strike = entry["strikePrice"]
            expiry_str = entry["expiryDate"]
            expiry = _parse_expiry(expiry_str)

            for side, key in (("CE", "CE"), ("PE", "PE")):
                if key not in entry:
                    continue
                leg = entry[key]
                records.append(
                    {
                        "symbol": symbol,
                        "strike": float(strike),
                        "expiry": expiry,
                        "option_type": side,
                        "oi": int(leg.get("openInterest", 0)),
                        "volume": int(leg.get("totalTradedVolume", 0)),
                        "last_price": float(leg.get("lastPrice", 0)),
                        "underlying_price": float(underlying),
                        "source_timestamp": source_timestamp,
                    }
                )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("NSE chain parse error", error=str(exc))
    return records


def _parse_expiry(expiry_str: str) -> date:
    from datetime import datetime

    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(expiry_str, fmt).date()
        except ValueError:
            continue
    return date.today()


def _parse_nse_source_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=IST).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


# ─── Zerodha Source ────────────────────────────────────────────────────────────


# Maps our symbol names to their Kite index quote keys
_ZERODHA_INDEX_QUOTE = {
    "NIFTY":     "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "SENSEX":    "BSE:SENSEX",
}


class ZerodhaDataSource:
    """Fetches option chain via Zerodha Kite Connect API."""

    def __init__(self) -> None:
        self._kite: Any = None
        self._instruments_cache: dict[str, list] = {}   # keyed by "EXCHANGE_date"
        self._instruments_cache_date: dict[str, Any] = {}

    def _get_kite(self) -> Any:
        if self._kite is None:
            from kiteconnect import KiteConnect  # type: ignore[import]

            kite = KiteConnect(api_key=settings.zerodha_api_key)
            kite.set_access_token(settings.zerodha_access_token)
            self._kite = kite
        return self._kite

    async def _get_instruments(self, loop, exchange: str = "NFO") -> list:
        """Cache instruments per exchange per day (NFO for NIFTY/BANKNIFTY, BFO for SENSEX)."""
        from datetime import date

        today = str(date.today())
        cache_key = f"{exchange}_{today}"
        if cache_key not in self._instruments_cache:
            kite = self._get_kite()
            logger.info("Fetching Zerodha instruments", exchange=exchange)
            instruments = await loop.run_in_executor(
                None, lambda: kite.instruments(exchange)
            )
            self._instruments_cache[cache_key] = instruments
        return self._instruments_cache[cache_key]

    async def _fetch_spot_price(self, symbol: str, kite: Any, loop) -> float:
        """Fetch the actual index spot price from NSE/BSE."""
        index_key = _ZERODHA_INDEX_QUOTE.get(symbol)
        if not index_key:
            return 0.0
        try:
            q = await loop.run_in_executor(None, lambda: kite.quote([index_key]))
            data = q.get(index_key, {})
            spot = float(
                data.get("last_price")
                or data.get("ohlc", {}).get("close", 0)
                or 0
            )
            logger.info("Fetched index spot", symbol=symbol, spot=spot)
            return spot
        except Exception as exc:
            logger.warning("Could not fetch index spot price", symbol=symbol, error=str(exc))
            return 0.0

    async def fetch_option_chain(self, symbol: str) -> list[dict[str, Any]]:
        # SENSEX options trade on BFO (BSE F&O), everything else on NFO
        exchange = "BFO" if symbol == "SENSEX" else "NFO"
        # BSE uses "SENSEX" as the name; NFO uses the symbol directly
        instr_name = "SENSEX" if symbol == "SENSEX" else symbol

        try:
            kite = self._get_kite()
            loop = asyncio.get_event_loop()

            instruments = await self._get_instruments(loop, exchange=exchange)

            # Filter to this symbol's options only (CE + PE)
            relevant = [
                inst for inst in instruments
                if inst.get("name") == instr_name
                and inst.get("instrument_type") in ("CE", "PE")
            ]
            # BFO SENSEX: some feeds use tradingsymbol prefix instead of name
            if not relevant and symbol == "SENSEX" and exchange == "BFO":
                relevant = [
                    inst for inst in instruments
                    if inst.get("instrument_type") in ("CE", "PE")
                    and (inst.get("name") == "SENSEX" or (isinstance(inst.get("tradingsymbol"), str) and inst["tradingsymbol"].upper().startswith("SENSEX")))
                ]
            if not relevant:
                sample = next((inst for inst in instruments[:50] if inst.get("instrument_type") in ("CE", "PE")), None)
                logger.warning(
                    "No Zerodha instruments found",
                    symbol=symbol,
                    exchange=exchange,
                    total_instruments=len(instruments),
                    sample_name=sample.get("name") if sample else None,
                    sample_tradingsymbol=sample.get("tradingsymbol") if sample else None,
                )
                return []

            # Fetch actual index spot price first
            spot_price = await self._fetch_spot_price(symbol, kite, loop)

            # Batch quote request — up to 400 symbols per call
            batch_size = 400
            all_quotes: dict = {}
            trading_symbols = [f"{exchange}:{inst['tradingsymbol']}" for inst in relevant]

            for i in range(0, len(trading_symbols), batch_size):
                batch = trading_symbols[i: i + batch_size]
                quotes = await loop.run_in_executor(
                    None, lambda b=batch: kite.quote(b)
                )
                all_quotes.update(quotes)

            records = []
            for inst in relevant:
                key = f"{exchange}:{inst['tradingsymbol']}"
                q = all_quotes.get(key, {})
                records.append(
                    {
                        "symbol": symbol,
                        "strike": float(inst["strike"]),
                        "expiry": inst["expiry"],
                        "option_type": inst["instrument_type"],
                        "oi": int(q.get("oi", 0)),
                        "volume": int(q.get("volume", 0)),
                        "last_price": float(q.get("last_price", 0)),
                        "underlying_price": spot_price,
                    }
                )
            logger.info(
                "Zerodha chain fetched",
                symbol=symbol,
                exchange=exchange,
                contracts=len(records),
                spot=spot_price,
            )
            return records
        except Exception as exc:
            logger.error("Zerodha fetch failed", symbol=symbol, error=str(exc))
            return []

    async def close(self) -> None:
        pass


# ─── Angel One Source ──────────────────────────────────────────────────────────


class AngelDataSource:
    """Fetches option chain via Angel One SmartAPI."""

    def __init__(self) -> None:
        self._obj: Any = None

    def _get_obj(self) -> Any:
        if self._obj is None:
            import pyotp  # type: ignore[import]
            from SmartApi import SmartConnect  # type: ignore[import]

            obj = SmartConnect(api_key=settings.angel_api_key)
            totp = pyotp.TOTP(settings.angel_totp_secret).now()
            obj.generateSession(settings.angel_client_id, settings.angel_password, totp)
            self._obj = obj
        return self._obj

    async def fetch_option_chain(self, symbol: str) -> list[dict[str, Any]]:
        try:
            loop = asyncio.get_event_loop()
            obj = self._get_obj()
            data = await loop.run_in_executor(
                None,
                lambda: obj.optionGreek({"name": symbol, "expirydate": ""}),
            )
            records = []
            for entry in data.get("data", []):
                records.append(
                    {
                        "symbol": symbol,
                        "strike": float(entry.get("strikePrice", 0)),
                        "expiry": _parse_expiry(entry.get("expiry", "")),
                        "option_type": entry.get("optionType", "CE"),
                        "oi": int(entry.get("openInterest", 0)),
                        "volume": int(entry.get("tradedVolume", 0)),
                        "last_price": float(entry.get("ltp", 0)),
                        "underlying_price": float(entry.get("underlyingValue", 0)),
                    }
                )
            return records
        except Exception as exc:
            logger.error("Angel fetch failed", symbol=symbol, error=str(exc))
            return []

    async def close(self) -> None:
        pass


# ─── Factory ───────────────────────────────────────────────────────────────────

_source_instance: DataSource | None = None


def get_data_source() -> DataSource:
    global _source_instance
    if _source_instance is None:
        match settings.data_source:
            case "ZERODHA":
                _source_instance = ZerodhaDataSource()
            case "ANGEL":
                _source_instance = AngelDataSource()
            case _:
                _source_instance = NSEDataSource()
        logger.info("Data source initialised", source=settings.data_source)
    return _source_instance
