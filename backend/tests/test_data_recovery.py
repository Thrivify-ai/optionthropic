import unittest
from datetime import datetime, timezone

from app.data_ingestion.data_recovery import needs_symbol_recovery


class DataRecoveryTests(unittest.TestCase):
    def test_recovery_needed_when_no_snapshot_exists(self) -> None:
        monday_open = datetime(2026, 3, 23, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
        self.assertTrue(needs_symbol_recovery(None, monday_open))

    def test_recovery_needed_for_missed_completed_day(self) -> None:
        tuesday_open = datetime(2026, 3, 24, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
        friday_closeish = datetime(2026, 3, 20, 9, 55, tzinfo=timezone.utc)  # 15:25 IST
        self.assertTrue(needs_symbol_recovery(friday_closeish, tuesday_open))

    def test_recovery_not_needed_when_latest_completed_day_is_present(self) -> None:
        monday_open = datetime(2026, 3, 23, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
        friday_closeish = datetime(2026, 3, 20, 9, 55, tzinfo=timezone.utc)  # 15:25 IST
        self.assertFalse(needs_symbol_recovery(friday_closeish, monday_open))


if __name__ == "__main__":
    unittest.main()
