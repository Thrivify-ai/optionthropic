import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

if "sqlalchemy" not in sys.modules:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.desc = lambda *args, **kwargs: None
    sqlalchemy_stub.select = lambda *args, **kwargs: None
    sqlalchemy_stub.func = types.SimpleNamespace(avg=lambda *args, **kwargs: None)
    sys.modules["sqlalchemy"] = sqlalchemy_stub

if "sqlalchemy.ext" not in sys.modules:
    sys.modules["sqlalchemy.ext"] = types.ModuleType("sqlalchemy.ext")

if "sqlalchemy.ext.asyncio" not in sys.modules:
    asyncio_stub = types.ModuleType("sqlalchemy.ext.asyncio")
    asyncio_stub.AsyncSession = object
    sys.modules["sqlalchemy.ext.asyncio"] = asyncio_stub

if "app.models.commodity_snapshot" not in sys.modules:
    commodity_snapshot_stub = types.ModuleType("app.models.commodity_snapshot")
    commodity_snapshot_stub.CommoditySnapshot = type(
        "CommoditySnapshot",
        (),
        {"price": None, "timestamp": None, "volume": None, "symbol": None},
    )
    sys.modules["app.models.commodity_snapshot"] = commodity_snapshot_stub

if "app.models.global_news_alert" not in sys.modules:
    global_news_stub = types.ModuleType("app.models.global_news_alert")
    global_news_stub.GlobalNewsAlert = type(
        "GlobalNewsAlert",
        (),
        {"impact_score": None, "fetched_at": None, "is_critical": None, "affected_symbols": None},
    )
    sys.modules["app.models.global_news_alert"] = global_news_stub

from app.analytics.commodity_signals import WindowSeries, commodity_long_term_signal, commodity_quick_signal


class CommoditySignalsTests(unittest.IsolatedAsyncioTestCase):
    async def test_quick_signal_requires_confirmed_burst(self) -> None:
        series = WindowSeries(
            current=6072.0,
            current_volume=210.0,
            prev_1m=6046.0,
            prev_3m=6038.0,
            prev_5m=6028.0,
            prev_30m=5980.0,
            prev_60m=5940.0,
            vol_5m_avg=120.0,
        )
        with patch("app.analytics.commodity_signals.get_series", AsyncMock(return_value=series)), patch(
            "app.analytics.commodity_signals._recent_prices",
            AsyncMock(return_value=[6072.0, 6060.0, 6048.0, 6036.0, 6028.0, 6020.0]),
        ):
            payload = await commodity_quick_signal(None, "CRUDEOIL")

        self.assertEqual(payload["signal"], "LONG")
        self.assertEqual(payload["state"], "active")
        self.assertTrue(payload["entry_ready"])
        self.assertGreaterEqual(payload["confidence"], 78)
        self.assertGreaterEqual(payload["confirmation_count"], payload["required_confirmations"])

    async def test_quick_signal_can_wait_as_setup(self) -> None:
        series = WindowSeries(
            current=6052.0,
            current_volume=110.0,
            prev_1m=6040.0,
            prev_3m=6030.0,
            prev_5m=6028.0,
            prev_30m=5980.0,
            prev_60m=5940.0,
            vol_5m_avg=100.0,
        )
        with patch("app.analytics.commodity_signals.get_series", AsyncMock(return_value=series)), patch(
            "app.analytics.commodity_signals._recent_prices",
            AsyncMock(return_value=[6052.0, 6046.0, 6040.0, 6035.0, 6030.0, 6028.0]),
        ):
            payload = await commodity_quick_signal(None, "CRUDEOIL")

        self.assertEqual(payload["signal"], "WAIT")
        self.assertEqual(payload["state"], "setup")
        self.assertEqual(payload["setup_direction"], "LONG")
        self.assertLess(payload["confidence"], 70)

    async def test_long_signal_requires_three_timeframe_alignment(self) -> None:
        series = WindowSeries(
            current=94850.0,
            current_volume=0.0,
            prev_1m=94810.0,
            prev_3m=94760.0,
            prev_5m=94740.0,
            prev_30m=94580.0,
            prev_60m=94480.0,
            vol_5m_avg=0.0,
        )
        with patch("app.analytics.commodity_signals.get_series", AsyncMock(return_value=series)), patch(
            "app.analytics.commodity_signals._recent_prices",
            AsyncMock(return_value=[94850.0, 94810.0, 94780.0, 94720.0, 94670.0, 94610.0, 94550.0]),
        ):
            payload = await commodity_long_term_signal(None, "GOLD")

        self.assertEqual(payload["signal"], "LONG")
        self.assertEqual(payload["state"], "active")
        self.assertGreaterEqual(payload["confidence"], 80)

    async def test_long_signal_can_hold_setup_without_entry(self) -> None:
        series = WindowSeries(
            current=94805.0,
            current_volume=0.0,
            prev_1m=94800.0,
            prev_3m=94780.0,
            prev_5m=94810.0,
            prev_30m=94580.0,
            prev_60m=94480.0,
            vol_5m_avg=0.0,
        )
        with patch("app.analytics.commodity_signals.get_series", AsyncMock(return_value=series)), patch(
            "app.analytics.commodity_signals._recent_prices",
            AsyncMock(return_value=[94805.0, 94795.0, 94785.0, 94770.0, 94740.0, 94710.0, 94680.0]),
        ):
            payload = await commodity_long_term_signal(None, "GOLD")

        self.assertEqual(payload["signal"], "WAIT")
        self.assertEqual(payload["state"], "setup")
        self.assertEqual(payload["setup_direction"], "LONG")


if __name__ == "__main__":
    unittest.main()
