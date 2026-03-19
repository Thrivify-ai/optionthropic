import unittest
from datetime import date, timedelta

from app.analytics.foundation_utils import (
    determine_dominant_flow,
    pcr_sentiment_from_value,
    select_representative_expiry,
)
from app.analytics.feature_utils import floor_to_minute, is_price_rangebound, merge_bar_ohlc


class AnalyticsFoundationTests(unittest.TestCase):
    def test_pcr_sentiment_uses_latest_thresholds(self) -> None:
        self.assertEqual(pcr_sentiment_from_value(1.31), "BULLISH")
        self.assertEqual(pcr_sentiment_from_value(0.69), "BEARISH")
        self.assertEqual(pcr_sentiment_from_value(1.0), "NEUTRAL")
        self.assertEqual(pcr_sentiment_from_value(None), "NEUTRAL")

    def test_select_representative_expiry_prefers_nearest_upcoming(self) -> None:
        today = date.today()
        results = [
            {"expiry": today + timedelta(days=7), "max_pain_strike": 22500.0},
            {"expiry": today + timedelta(days=35), "max_pain_strike": 23000.0},
            {"expiry": today - timedelta(days=1), "max_pain_strike": 22300.0},
        ]
        chosen = select_representative_expiry(results)
        self.assertEqual(chosen["expiry"], today + timedelta(days=7))

    def test_select_representative_expiry_uses_most_recent_past_when_needed(self) -> None:
        results = [
            {"expiry": date(2025, 12, 18), "max_pain_strike": 22000.0},
            {"expiry": date(2026, 1, 29), "max_pain_strike": 22500.0},
        ]
        chosen = select_representative_expiry(results)
        self.assertEqual(chosen["expiry"], date(2026, 1, 29))

    def test_dominant_flow_infers_direction_from_premium_imbalance(self) -> None:
        self.assertEqual(determine_dominant_flow(100.0, 200.0), "put_writing")
        self.assertEqual(determine_dominant_flow(200.0, 100.0), "call_writing")
        self.assertEqual(determine_dominant_flow(100.0, 120.0), "put_buying")
        self.assertEqual(determine_dominant_flow(120.0, 100.0), "call_buying")
        self.assertEqual(determine_dominant_flow(100.0, 105.0), "mixed")

    def test_merge_bar_ohlc_initializes_and_updates(self) -> None:
        created = merge_bar_ohlc(None, 100.0)
        self.assertEqual(created, {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0})

        updated = merge_bar_ohlc(created, 103.0)
        self.assertEqual(updated["open"], 100.0)
        self.assertEqual(updated["high"], 103.0)
        self.assertEqual(updated["low"], 100.0)
        self.assertEqual(updated["close"], 103.0)

    def test_price_rangebound_thresholds_are_timeframe_aware(self) -> None:
        self.assertTrue(is_price_rangebound("5m", 0.0010))
        self.assertFalse(is_price_rangebound("5m", 0.0020))
        self.assertTrue(is_price_rangebound("60m", 0.0030))

    def test_floor_to_minute_removes_seconds(self) -> None:
        from datetime import datetime, timezone

        ts = datetime(2026, 3, 19, 10, 15, 42, 123456, tzinfo=timezone.utc)
        floored = floor_to_minute(ts)
        self.assertEqual(floored.second, 0)
        self.assertEqual(floored.microsecond, 0)
        self.assertEqual(floored.minute, 15)


if __name__ == "__main__":
    unittest.main()
