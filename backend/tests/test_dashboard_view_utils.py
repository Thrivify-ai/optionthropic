import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.analytics.dashboard_view_utils import (
    mark_payload_stale,
    serialize_trading_signal_payload,
    summary_payload_from_cache,
)


class DashboardViewUtilsTests(unittest.TestCase):
    def test_serialize_trading_signal_payload_defaults_to_wait(self) -> None:
        payload = serialize_trading_signal_payload(None)
        self.assertEqual(payload["signal"], "Wait")
        self.assertEqual(payload["confidence"], 0)
        self.assertEqual(payload["outlook"], "Neutral")
        self.assertEqual(payload["state"], "idle")

    def test_summary_payload_from_cache_marks_missing_summary_pending(self) -> None:
        payload = summary_payload_from_cache(None)
        self.assertTrue(payload["pending"])
        self.assertFalse(payload["cached"])

    def test_mark_payload_stale_sets_flag_for_old_rows(self) -> None:
        now = datetime.now(timezone.utc)
        payload = mark_payload_stale(
            {"symbol": "NIFTY"},
            now - timedelta(minutes=5),
            now=now,
            max_age=timedelta(seconds=90),
        )
        self.assertTrue(payload["stale"])

    def test_serialize_trading_signal_payload_uses_row_values(self) -> None:
        row = SimpleNamespace(
            signal="Buy CE",
            confidence=81,
            support=22450.0,
            resistance=22600.0,
            bias_5m="Bullish",
            bias_30m="Bullish",
            bias_60m="Bullish",
            reason="Aligned and confirmed.",
        )
        payload = serialize_trading_signal_payload(row)
        self.assertEqual(payload["signal"], "Buy CE")
        self.assertEqual(payload["confidence"], 81)
        self.assertEqual(payload["support"], 22450.0)
        self.assertEqual(payload["outlook"], "Bullish")
        self.assertEqual(payload["state"], "active")


if __name__ == "__main__":
    unittest.main()
