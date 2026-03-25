import unittest
import importlib
import sys
import types
from unittest.mock import patch


class _DummyLogger:
    def info(self, *args, **kwargs) -> None:
        return None

    def warning(self, *args, **kwargs) -> None:
        return None

    def debug(self, *args, **kwargs) -> None:
        return None


sys.modules.setdefault(
    "app.config",
    types.SimpleNamespace(
        settings=types.SimpleNamespace(
            zerodha_api_key="",
            zerodha_access_token="",
            fast_tick_poll_seconds=5,
        )
    ),
)
sys.modules.setdefault(
    "app.logging_config",
    types.SimpleNamespace(get_logger=lambda _name: _DummyLogger()),
)

tick_stream = importlib.import_module("app.services.tick_stream")


class TickStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        tick_stream._tick_store.clear()
        with tick_stream._history_lock:
            tick_stream._tick_history.clear()

    def test_price_seconds_ago_uses_closest_fresh_sample(self) -> None:
        base = 1_700_000_000.0
        tick_stream._record_price_point(
            "NIFTY",
            price=23_430.0,
            change=0.0,
            timestamp_iso="2026-03-25T08:30:00+00:00",
            epoch_seconds=base - 20,
        )
        tick_stream._record_price_point(
            "NIFTY",
            price=23_420.0,
            change=-10.0,
            timestamp_iso="2026-03-25T08:30:10+00:00",
            epoch_seconds=base - 10,
        )
        tick_stream._record_price_point(
            "NIFTY",
            price=23_410.0,
            change=-20.0,
            timestamp_iso="2026-03-25T08:30:20+00:00",
            epoch_seconds=base,
        )

        with patch("app.services.tick_stream.time.time", return_value=base):
            self.assertEqual(tick_stream.get_price_seconds_ago("NIFTY", 10), 23420.0)
            self.assertEqual(tick_stream.get_price_seconds_ago("NIFTY", 20), 23430.0)

    def test_price_seconds_ago_returns_none_when_history_is_too_sparse(self) -> None:
        base = 1_700_000_100.0
        tick_stream._record_price_point(
            "BANKNIFTY",
            price=54_000.0,
            change=0.0,
            timestamp_iso="2026-03-25T08:31:00+00:00",
            epoch_seconds=base - 40,
        )
        tick_stream._record_price_point(
            "BANKNIFTY",
            price=53_980.0,
            change=-20.0,
            timestamp_iso="2026-03-25T08:31:40+00:00",
            epoch_seconds=base,
        )

        with patch("app.services.tick_stream.time.time", return_value=base):
            self.assertIsNone(tick_stream.get_price_seconds_ago("BANKNIFTY", 10, tolerance_seconds=4))


if __name__ == "__main__":
    unittest.main()
