import unittest

from app.analytics.volatility_profile import IntradayVolatilityProfile, scale_threshold, scale_trade_thresholds


class VolatilityProfileTests(unittest.TestCase):
    def test_scale_threshold_respects_dynamic_component(self) -> None:
        profile = IntradayVolatilityProfile(
            symbol="NIFTY",
            baseline_abs_move_1m=9.0,
            avg_abs_move_1m=14.0,
            avg_true_range_1m=18.0,
            realized_move_5m=42.0,
            ratio_to_baseline=1.55,
            sample_size=18,
        )

        scaled = scale_threshold(18.0, profile, multiplier=1.4)

        self.assertGreater(scaled, 18.0)
        self.assertLessEqual(scaled, 18.0 * 1.8)

    def test_scale_trade_thresholds_expand_in_fast_tape(self) -> None:
        success, stop = scale_trade_thresholds(
            base_success=10.0,
            base_stop=8.0,
            volatility_ratio=1.4,
            event_risk=True,
        )

        self.assertGreater(success, 10.0)
        self.assertGreater(stop, 8.0)


if __name__ == "__main__":
    unittest.main()
