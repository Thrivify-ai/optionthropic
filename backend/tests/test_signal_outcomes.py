import unittest
from types import SimpleNamespace

from app.analytics.signal_outcomes import (
    CalibrationRow,
    classify_outcome,
    confidence_bucket,
    preferred_outcome_for_engine,
    summarize_calibration,
)


class SignalOutcomeTests(unittest.TestCase):
    def test_classify_outcome_respects_signal_direction(self) -> None:
        self.assertEqual(classify_outcome("Buy CE", 100.0, 103.0), "Won")
        self.assertEqual(classify_outcome("Buy CE", 100.0, 98.0), "Lost")
        self.assertEqual(classify_outcome("Buy PE", 100.0, 97.0), "Won")
        self.assertEqual(classify_outcome("Buy PE", 100.0, 103.0), "Lost")

    def test_confidence_bucket_groups_ranges(self) -> None:
        self.assertEqual(confidence_bucket(42), "0-49")
        self.assertEqual(confidence_bucket(55), "50-59")
        self.assertEqual(confidence_bucket(87), "80-89")

    def test_preferred_outcome_uses_engine_specific_horizons(self) -> None:
        quick_row = SimpleNamespace(outcome_2m="Unknown", outcome_3m="Won")
        long_row = SimpleNamespace(outcome_5m="Unknown", outcome_10m="Unknown", outcome_30m="Lost")

        self.assertEqual(preferred_outcome_for_engine("QUICK", quick_row), "Won")
        self.assertEqual(preferred_outcome_for_engine("MAIN", long_row), "Lost")

    def test_summarize_calibration_aggregates_win_rates(self) -> None:
        rows = [
            CalibrationRow("QUICK", 72, "Won"),
            CalibrationRow("QUICK", 75, "Lost"),
            CalibrationRow("QUICK", 75, "Unknown"),
            CalibrationRow("MAIN", 84, "Won"),
            CalibrationRow("MAIN", 84, "Won"),
        ]

        summary = summarize_calibration(rows)
        quick_bucket = next(item for item in summary if item["engine"] == "QUICK" and item["bucket"] == "70-79")
        main_bucket = next(item for item in summary if item["engine"] == "MAIN" and item["bucket"] == "80-89")

        self.assertEqual(quick_bucket["total"], 3)
        self.assertEqual(quick_bucket["won"], 1)
        self.assertEqual(quick_bucket["lost"], 1)
        self.assertEqual(quick_bucket["win_rate_pct"], 50.0)
        self.assertEqual(main_bucket["win_rate_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
