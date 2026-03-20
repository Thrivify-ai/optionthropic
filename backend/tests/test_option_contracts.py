import unittest
from datetime import date, datetime, timezone

from app.analytics.option_contracts import _pick_expiry, _quality, contract_type_for_signal


class OptionContractsTests(unittest.TestCase):
    def test_contract_type_matches_signal(self) -> None:
        self.assertEqual(contract_type_for_signal("Buy CE"), "CE")
        self.assertEqual(contract_type_for_signal("Buy PE"), "PE")
        self.assertIsNone(contract_type_for_signal("Wait"))

    def test_pick_expiry_moves_out_on_same_day_afternoon(self) -> None:
        expiries = [date(2026, 3, 20), date(2026, 3, 27)]
        morning = datetime(2026, 3, 20, 4, 0, tzinfo=timezone.utc)
        afternoon = datetime(2026, 3, 20, 8, 30, tzinfo=timezone.utc)

        self.assertEqual(_pick_expiry(expiries, morning, "QUICK"), date(2026, 3, 20))
        self.assertEqual(_pick_expiry(expiries, afternoon, "MAIN"), date(2026, 3, 27))
        self.assertEqual(_pick_expiry(expiries, afternoon, "QUICK"), date(2026, 3, 27))

    def test_quality_uses_liquidity_and_premium(self) -> None:
        self.assertEqual(_quality(15000, 8000, 35.0), "HIGH")
        self.assertEqual(_quality(4000, 1200, 14.0), "MEDIUM")
        self.assertEqual(_quality(500, 100, 6.0), "LOW")


if __name__ == "__main__":
    unittest.main()
