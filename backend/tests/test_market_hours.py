import unittest
from datetime import date, datetime, timezone

from app.services.market_hours import (
    get_equity_market_status,
    get_mcx_market_status,
    global_news_poll_interval_seconds,
    ai_cache_ttl_seconds,
    dashboard_cache_ttl_seconds,
    global_news_cache_ttl_seconds,
    is_indian_market_open,
    is_market_news_window_open,
    is_mcx_market_open,
    latest_completed_trading_day,
    needs_completed_day_refresh,
    previous_trading_day,
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

    def test_equity_holiday_closes_market_on_weekday(self) -> None:
        ram_navami = datetime(2026, 3, 26, 5, 30, tzinfo=timezone.utc)  # 11:00 IST
        status = get_equity_market_status(ram_navami)
        self.assertFalse(is_indian_market_open(ram_navami))
        self.assertFalse(should_refresh_intraday_caches(ram_navami))
        self.assertTrue(status.is_holiday)
        self.assertIn("Ram Navami", status.reason)

    def test_mcx_evening_session_can_open_on_equity_holiday(self) -> None:
        ram_navami_evening = datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc)  # 17:30 IST
        status = get_mcx_market_status(ram_navami_evening)
        self.assertTrue(is_mcx_market_open(ram_navami_evening))
        self.assertTrue(status.is_open)
        self.assertEqual(status.session, "EVENING")

    def test_global_news_refreshes_fast_during_mcx_evening_session(self) -> None:
        ram_navami_evening = datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc)  # 17:30 IST
        sunday_closed = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)

        self.assertTrue(is_market_news_window_open(ram_navami_evening))
        self.assertFalse(is_indian_market_open(ram_navami_evening))
        self.assertLess(
            global_news_poll_interval_seconds(ram_navami_evening),
            global_news_poll_interval_seconds(sunday_closed),
        )
        self.assertLess(
            global_news_cache_ttl_seconds(ram_navami_evening),
            global_news_cache_ttl_seconds(sunday_closed),
        )

    def test_cache_ttls_change_by_market_state(self) -> None:
        monday_open = datetime(2026, 3, 23, 4, 30, tzinfo=timezone.utc)
        sunday_closed = datetime(2026, 3, 22, 4, 30, tzinfo=timezone.utc)
        self.assertLess(dashboard_cache_ttl_seconds(monday_open), dashboard_cache_ttl_seconds(sunday_closed))
        self.assertLess(ai_cache_ttl_seconds(monday_open), ai_cache_ttl_seconds(sunday_closed))

    def test_previous_trading_day_skips_weekend(self) -> None:
        self.assertEqual(previous_trading_day(date(2026, 3, 23)), date(2026, 3, 20))

    def test_latest_completed_trading_day_is_previous_day_before_close(self) -> None:
        monday_mid_session = datetime(2026, 3, 23, 5, 30, tzinfo=timezone.utc)  # 11:00 IST
        self.assertEqual(latest_completed_trading_day(monday_mid_session), date(2026, 3, 20))

    def test_latest_completed_trading_day_is_today_after_close(self) -> None:
        monday_after_close = datetime(2026, 3, 23, 11, 30, tzinfo=timezone.utc)  # 17:00 IST
        self.assertEqual(latest_completed_trading_day(monday_after_close), date(2026, 3, 23))

    def test_completed_day_refresh_triggers_when_latest_snapshot_is_stale(self) -> None:
        monday_after_close = datetime(2026, 3, 23, 11, 30, tzinfo=timezone.utc)  # 17:00 IST
        stale_snapshot = datetime(2026, 3, 23, 8, 0, tzinfo=timezone.utc)  # 13:30 IST
        self.assertTrue(needs_completed_day_refresh(stale_snapshot, monday_after_close))

    def test_completed_day_refresh_skips_when_snapshot_near_session_close(self) -> None:
        monday_after_close = datetime(2026, 3, 23, 11, 30, tzinfo=timezone.utc)  # 17:00 IST
        fresh_snapshot = datetime(2026, 3, 23, 9, 55, tzinfo=timezone.utc)  # 15:25 IST
        self.assertFalse(needs_completed_day_refresh(fresh_snapshot, monday_after_close))


if __name__ == "__main__":
    unittest.main()
