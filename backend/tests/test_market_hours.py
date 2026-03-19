import unittest
from datetime import datetime, timezone

from app.services.market_hours import (
    ai_cache_ttl_seconds,
    dashboard_cache_ttl_seconds,
    is_indian_market_open,
    should_refresh_intraday_caches,
)


class MarketHoursTests(unittest.TestCase):
    def test_market_is_open_during_weekday_session(self) -> None:
        monday_open = datetime(2026, 3, 23, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
        self.assertTrue(is_indian_market_open(monday_open))
        self.assertTrue(should_refresh_intraday_caches(monday_open))

    def test_market_is_closed_after_hours(self) -> None:
        monday_closed = datetime(2026, 3, 23, 11, 30, tzinfo=timezone.utc)  # 17:00 IST
        self.assertFalse(is_indian_market_open(monday_closed))

    def test_market_is_closed_on_weekends(self) -> None:
        saturday = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)  # 10:30 IST
        self.assertFalse(is_indian_market_open(saturday))

    def test_cache_ttls_change_by_market_state(self) -> None:
        monday_open = datetime(2026, 3, 23, 4, 30, tzinfo=timezone.utc)
        sunday_closed = datetime(2026, 3, 22, 4, 30, tzinfo=timezone.utc)
        self.assertLess(dashboard_cache_ttl_seconds(monday_open), dashboard_cache_ttl_seconds(sunday_closed))
        self.assertLess(ai_cache_ttl_seconds(monday_open), ai_cache_ttl_seconds(sunday_closed))


if __name__ == "__main__":
    unittest.main()
