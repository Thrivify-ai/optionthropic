import unittest

from app.analytics.quant_signal_capture import QuantContextFields, derive_shadow_signal


class QuantSignalCaptureTests(unittest.TestCase):
    def test_shadow_model_suppresses_high_risk_live_signal(self) -> None:
        context = QuantContextFields(
            session_bucket="OPENING",
            vol_regime="HIGH",
            breakout_class="FAILED_BREAK",
            expiry_bucket="0DTE",
            regime_label="REVERSAL",
            days_to_expiry=0,
            is_expiry_day=True,
            open_gap_pct=0.8,
            data_freshness_seconds=20.0,
            snapshot_spacing_std_seconds=4.0,
            short_covering_risk_score=82,
            trap_score=90,
            wall_shift_score=12,
        )

        signal, confidence, reason = derive_shadow_signal(
            engine="QUICK",
            signal="Buy CE",
            confidence=84,
            context=context,
            entry_ready=True,
            raw_signal="Buy CE",
        )

        self.assertEqual(signal, "Wait")
        self.assertLess(confidence, 84)
        self.assertIn("risk", reason.lower())

    def test_shadow_quick_can_promote_raw_impulse_when_live_is_wait(self) -> None:
        context = QuantContextFields(
            session_bucket="OPENING",
            vol_regime="HIGH",
            breakout_class="CLEAN_BREAK",
            expiry_bucket="2_5DTE",
            regime_label="TREND_UP",
            days_to_expiry=2,
            is_expiry_day=False,
            open_gap_pct=0.2,
            data_freshness_seconds=10.0,
            snapshot_spacing_std_seconds=2.0,
            short_covering_risk_score=10,
            trap_score=0,
            wall_shift_score=6,
        )

        signal, confidence, _ = derive_shadow_signal(
            engine="QUICK",
            signal="Wait",
            confidence=88,
            context=context,
            entry_ready=False,
            raw_signal="Buy PE",
        )

        self.assertEqual(signal, "Buy PE")
        self.assertGreaterEqual(confidence, 82)


if __name__ == "__main__":
    unittest.main()
