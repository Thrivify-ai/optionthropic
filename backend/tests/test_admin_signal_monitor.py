import unittest
from decimal import Decimal

from app.analytics.admin_signal_monitor import (
    clean_entry_block_reason,
    serialize_managed_daily_rows,
    summarize_decision_rows,
    summarize_entry_block_rows,
)


class AdminSignalMonitorTests(unittest.TestCase):
    def test_summarize_decision_rows_builds_buy_wait_mix(self) -> None:
        rows = [
            {"engine": "QUICK", "signal": "Buy CE", "total": 12, "avg_confidence": 82.0},
            {"engine": "QUICK", "signal": "Wait", "total": 18, "avg_confidence": 74.0},
            {"engine": "MAIN", "signal": "Buy PE", "total": 5, "avg_confidence": 88.0},
            {"engine": "COMMODITY_QUICK", "signal": "LONG", "total": 2, "avg_confidence": 84.0},
            {"engine": "COMMODITY_QUICK", "signal": "HOLD LONG", "total": 3, "avg_confidence": 80.0},
        ]

        summary = summarize_decision_rows(rows)

        self.assertEqual(summary["QUICK"]["total"], 30)
        self.assertEqual(summary["QUICK"]["trade_event_total"], 12)
        self.assertEqual(summary["QUICK"]["entry_total"], 12)
        self.assertEqual(summary["QUICK"]["no_trade_total"], 18)
        self.assertEqual(summary["QUICK"]["buy_ce"], 12)
        self.assertEqual(summary["QUICK"]["buy_total"], 12)
        self.assertEqual(summary["QUICK"]["wait"], 18)
        self.assertEqual(summary["QUICK"]["buy_share_pct"], 40.0)
        self.assertEqual(summary["QUICK"]["entry_share_pct"], 100.0)
        self.assertEqual(summary["QUICK"]["avg_confidence"], 77.2)
        self.assertEqual(summary["MAIN"]["buy_pe"], 5)
        self.assertEqual(summary["MAIN"]["wait"], 0)
        self.assertEqual(summary["COMMODITY_QUICK"]["long"], 2)
        self.assertEqual(summary["COMMODITY_QUICK"]["hold"], 3)
        self.assertEqual(summary["COMMODITY_QUICK"]["buy_total"], 2)
        self.assertEqual(summary["COMMODITY_QUICK"]["trade_event_total"], 5)
        self.assertEqual(summary["COMMODITY_QUICK"]["entry_share_pct"], 40.0)

    def test_clean_and_summarize_entry_block_reasons(self) -> None:
        rows = [
            {"engine": "QUICK", "reason": "Entry blocked: Session gate failed", "total": 4},
            {"engine": "QUICK", "reason": " Entry   blocked: Session gate failed ", "total": 1},
            {"engine": "QUICK", "reason": "Entry blocked: Freshness gate failed", "total": 2},
            {"engine": "MAIN", "reason": "Entry blocked: Breadth gate failed", "total": 3},
        ]

        self.assertEqual(clean_entry_block_reason("Entry blocked:   Session gate failed"), "Session gate failed")

        summary = summarize_entry_block_rows(rows, top_n=2)

        self.assertEqual(summary["QUICK"]["total"], 7)
        self.assertEqual(summary["QUICK"]["top_reasons"][0]["reason"], "Session gate failed")
        self.assertEqual(summary["QUICK"]["top_reasons"][0]["count"], 5)
        self.assertEqual(summary["MAIN"]["top_reasons"][0]["reason"], "Breadth gate failed")

    def test_serialize_managed_daily_rows_formats_win_rate_and_points(self) -> None:
        rows = [
            {
                "trade_day": "2026-04-01",
                "engine": "QUICK",
                "total": 6,
                "won": 3,
                "lost": 2,
                "scratch": 1,
                "net_points": Decimal("23.45"),
                "avg_points": Decimal("3.91"),
            }
        ]

        serialized = serialize_managed_daily_rows(rows)

        self.assertEqual(len(serialized), 1)
        self.assertEqual(serialized[0]["trade_day"], "2026-04-01")
        self.assertEqual(serialized[0]["engine"], "QUICK")
        self.assertEqual(serialized[0]["win_rate_pct"], 50.0)
        self.assertEqual(serialized[0]["net_points"], 23.45)
        self.assertEqual(serialized[0]["avg_points"], 3.91)


if __name__ == "__main__":
    unittest.main()
