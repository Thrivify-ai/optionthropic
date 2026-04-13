import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.analytics.signal_outcomes import (
    CalibrationRow,
    classify_managed_exit_type,
    classify_outcome,
    confidence_bucket,
    managed_summary_by_engine,
    managed_trade_duration_seconds,
    preferred_outcome_for_engine,
    serialize_managed_trade_row,
    summarize_calibration,
    summarize_managed_trades,
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

    def test_summarize_managed_trades_by_engine(self) -> None:
        entry_time = datetime(2026, 4, 10, 4, 0, tzinfo=timezone.utc)
        exit_time = datetime(2026, 4, 10, 4, 3, 30, tzinfo=timezone.utc)
        rows = [
            SimpleNamespace(
                engine="QUICK",
                status="CLOSED",
                result_label="Won",
                realized_points=12.0,
                entry_time=entry_time,
                exit_time=exit_time,
                exit_reason="Trailing protection hit after giving back 5 points from peak.",
                latest_reason=None,
                exit_signal="Exit CE",
            ),
            SimpleNamespace(
                engine="QUICK",
                status="CLOSED",
                result_label="Lost",
                realized_points=-4.0,
                entry_time=entry_time,
                exit_time=exit_time,
                exit_reason="Stop triggered after -4 points against the trade.",
                latest_reason=None,
                exit_signal="Exit PE",
            ),
            SimpleNamespace(engine="COMMODITY_QUICK", status="OPEN", result_label=None, realized_points=None),
        ]

        quick_summary = summarize_managed_trades(rows[:2])
        by_engine = managed_summary_by_engine(rows)

        self.assertEqual(quick_summary["total"], 2)
        self.assertEqual(quick_summary["closed"], 2)
        self.assertEqual(quick_summary["protective_exits"], 2)
        self.assertEqual(quick_summary["win_rate_pct"], 50.0)
        self.assertEqual(quick_summary["net_points"], 8.0)
        self.assertEqual(quick_summary["avg_duration_seconds"], 210.0)
        self.assertEqual(quick_summary["avg_duration_label"], "3m 30s")
        self.assertEqual(by_engine["COMMODITY_QUICK"]["open"], 1)

    def test_managed_trade_serialization_tracks_exit_lifecycle(self) -> None:
        row = SimpleNamespace(
            id=42,
            engine="QUICK",
            symbol="NIFTY",
            entry_signal="Buy CE",
            latest_signal="Exit CE",
            status="CLOSED",
            entry_confidence=91,
            latest_confidence=78,
            exit_confidence=78,
            entry_price=23300.0,
            latest_price=23352.0,
            latest_points=52.0,
            success_threshold_points=10.0,
            stop_points=8.0,
            max_favorable_points=70.0,
            max_adverse_points=-2.0,
            hold_cycles=4,
            exit_signal="Exit CE",
            exit_price=23352.0,
            realized_points=52.0,
            result_label="Won",
            entry_time=datetime(2026, 4, 10, 4, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 4, 10, 4, 5, tzinfo=timezone.utc),
            entry_reason="Momentum breakout.",
            exit_reason="Opposite move has high conviction (82%) and persistence - exit the current trade.",
            latest_reason=None,
        )

        serialized = serialize_managed_trade_row(row)

        self.assertEqual(managed_trade_duration_seconds(row), 300)
        self.assertEqual(classify_managed_exit_type(row), "Opposite Move")
        self.assertEqual(serialized["trade_duration_label"], "5m")
        self.assertEqual(serialized["captured_points"], 52.0)
        self.assertEqual(serialized["giveback_points"], 18.0)
        self.assertTrue(serialized["protective_exit"])


if __name__ == "__main__":
    unittest.main()
