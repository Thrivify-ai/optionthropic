import unittest
from datetime import datetime, timezone

from app.analytics.quant_signal_context import (
    classify_breakout_class,
    classify_option_outcome,
    classify_regime_label,
    classify_underlying_outcome,
    classify_vol_regime,
    expiry_bucket,
    score_short_covering_risk,
    score_trap,
    session_bucket,
    wall_shift_score,
)


class QuantSignalContextTests(unittest.TestCase):
    def test_session_bucket_uses_indian_market_windows(self) -> None:
        opening = datetime(2026, 3, 20, 4, 10, tzinfo=timezone.utc)
        midday = datetime(2026, 3, 20, 7, 0, tzinfo=timezone.utc)
        closing = datetime(2026, 3, 20, 9, 30, tzinfo=timezone.utc)
        weekend = datetime(2026, 3, 21, 6, 0, tzinfo=timezone.utc)

        self.assertEqual(session_bucket(opening), "OPENING")
        self.assertEqual(session_bucket(midday), "MIDDAY")
        self.assertEqual(session_bucket(closing), "CLOSING")
        self.assertEqual(session_bucket(weekend), "CLOSED")

    def test_expiry_bucket_groups_days(self) -> None:
        self.assertEqual(expiry_bucket(0), "0DTE")
        self.assertEqual(expiry_bucket(1), "1DTE")
        self.assertEqual(expiry_bucket(3), "2_5DTE")
        self.assertEqual(expiry_bucket(8), "GT5DTE")

    def test_underlying_and_option_outcomes_use_correct_direction_rules(self) -> None:
        self.assertEqual(classify_underlying_outcome("Buy CE", 100.0, 102.0), "Won")
        self.assertEqual(classify_underlying_outcome("Buy PE", 100.0, 102.0), "Lost")
        self.assertEqual(classify_option_outcome(20.0, 25.0), "Won")
        self.assertEqual(classify_option_outcome(20.0, 18.0), "Lost")

    def test_breakout_and_regime_labels_reflect_structure(self) -> None:
        breakout = classify_breakout_class(
            signal="Buy CE",
            breakout=True,
            breakdown=False,
            support=22100.0,
            resistance=22200.0,
            current_price=22220.0,
            momentum=35.0,
            trap_detected=False,
        )
        trap = classify_breakout_class(
            signal="Buy CE",
            breakout=True,
            breakdown=False,
            support=22100.0,
            resistance=22200.0,
            current_price=22190.0,
            momentum=12.0,
            trap_detected=True,
        )

        self.assertEqual(breakout, "CLEAN_BREAK")
        self.assertEqual(trap, "FAILED_BREAK")
        self.assertEqual(
            classify_regime_label(
                engine="MAIN",
                signal="Buy CE",
                outlook="Bullish",
                state="active",
                entry_ready=True,
                rangebound=False,
                trap_detected=False,
                expiry_bucket_value="2_5DTE",
                breakout_class=breakout,
            ),
            "TREND_UP",
        )

    def test_scores_penalize_covering_and_traps(self) -> None:
        covering = score_short_covering_risk(
            signal="Buy CE",
            call_oi_delta=-1200,
            put_oi_delta=-100,
            breakout=True,
            breakdown=False,
            volume_spike=False,
            writer_support=False,
        )
        clean = score_short_covering_risk(
            signal="Buy CE",
            call_oi_delta=-800,
            put_oi_delta=1600,
            breakout=True,
            breakdown=False,
            volume_spike=True,
            writer_support=True,
        )
        trap_score = score_trap(
            trap_detected=True,
            rangebound=False,
            breakout_class="FAILED_BREAK",
        )

        self.assertGreater(covering, clean)
        self.assertEqual(trap_score, 100)

    def test_vol_regime_and_wall_shift_are_bounded(self) -> None:
        self.assertEqual(classify_vol_regime("NIFTY", quick_momentum=10.0), "LOW")
        self.assertEqual(classify_vol_regime("NIFTY", quick_momentum=55.0), "HIGH")
        self.assertEqual(wall_shift_score(22100.0, 22050.0, 22300.0, 22220.0), 100)


if __name__ == "__main__":
    unittest.main()
