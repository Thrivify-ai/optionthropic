import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

if "pydantic_settings" not in sys.modules:
    settings_stub = types.ModuleType("pydantic_settings")

    class BaseSettings:
        def __init__(self, *args, **kwargs):
            for name, value in self.__class__.__dict__.items():
                if name.startswith("_") or callable(value) or isinstance(value, property):
                    continue
                setattr(self, name, value)

    class SettingsConfigDict(dict):
        pass

    settings_stub.BaseSettings = BaseSettings
    settings_stub.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = settings_stub

if "app.logging_config" not in sys.modules:
    logging_stub = types.ModuleType("app.logging_config")

    class _Logger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

    logging_stub.get_logger = lambda name: _Logger()
    sys.modules["app.logging_config"] = logging_stub

from app.analytics.quick_signal_cache import cache_quick_signal_payload, get_cached_quick_signal_payload


class QuickSignalCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_round_trip_returns_recent_payload(self) -> None:
        symbol = "NIFTY"
        payload = {
            "symbol": symbol,
            "quick_signal": "Buy PE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await cache_quick_signal_payload(symbol, payload)
        cached = await get_cached_quick_signal_payload(symbol, max_age_seconds=30)

        self.assertIsNotNone(cached)
        self.assertEqual(cached["quick_signal"], "Buy PE")
        self.assertTrue(cached["cached"])

    async def test_cache_ignores_stale_payload(self) -> None:
        symbol = "BANKNIFTY"
        payload = {
            "symbol": symbol,
            "quick_signal": "Wait",
            "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(),
        }

        await cache_quick_signal_payload(symbol, payload)
        cached = await get_cached_quick_signal_payload(symbol, max_age_seconds=20)

        self.assertIsNone(cached)
