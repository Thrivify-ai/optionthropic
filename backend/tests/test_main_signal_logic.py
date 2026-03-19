import unittest

from app.analytics.main_signal_logic import FeatureView, generate_main_signal_from_features


def _feature(
    timeframe: str,
    *,
    current_price: float = 100.0,
    prev_price: float = 99.0,
    pcr_oi: float | None = 1.2,
    writer_bullish_score: int = 1,
    writer_bearish_score: int = 0,
    position_buildup: str | None = "Long buildup",
    volume_spike: bool = True,
    price_rangebound: bool = False,
    rangebound_oi_both_sides: bool = False,
    breakout_flag: bool = True,
    breakdown_flag: bool = False,
    trap_warning_flag: bool = False,
) -> FeatureView:
    return FeatureView(
        timeframe=timeframe,
        current_price=current_price,
        prev_price=prev_price,
        pcr_oi=pcr_oi,
        support_strike=95.0,
        resistance_strike=105.0,
        near_support_put_oi_change=10,
        near_resistance_call_oi_change=-5,
        writer_bullish_score=writer_bullish_score,
        writer_bearish_score=writer_bearish_score,
        position_buildup=position_buildup,
        volume_spike=volume_spike,
        price_rangebound=price_rangebound,
        rangebound_oi_both_sides=rangebound_oi_both_sides,
        breakout_flag=breakout_flag,
        breakdown_flag=breakdown_flag,
        trap_warning_flag=trap_warning_flag,
    )


class MainSignalLogicTests(unittest.TestCase):
    def test_emits_buy_ce_when_aligned_and_persistent(self) -> None:
        current = (_feature("5m"), _feature("30m"), _feature("60m"))
        previous = (_feature("5m"), _feature("30m"), _feature("60m"))
        result = generate_main_signal_from_features("NIFTY", current, previous)
        self.assertEqual(result.signal.value, "Buy CE")
        self.assertGreaterEqual(result.confidence, 70)

    def test_waits_when_alignment_has_not_persisted(self) -> None:
        current = (_feature("5m"), _feature("30m"), _feature("60m"))
        previous = (
            _feature("5m", current_price=99.0, prev_price=100.0, pcr_oi=0.8, writer_bullish_score=0, writer_bearish_score=1, position_buildup="Short buildup", breakout_flag=False, breakdown_flag=True),
            _feature("30m", current_price=99.0, prev_price=100.0, pcr_oi=0.8, writer_bullish_score=0, writer_bearish_score=1, position_buildup="Short buildup", breakout_flag=False, breakdown_flag=True),
            _feature("60m", current_price=99.0, prev_price=100.0, pcr_oi=0.8, writer_bullish_score=0, writer_bearish_score=1, position_buildup="Short buildup", breakout_flag=False, breakdown_flag=True),
        )
        result = generate_main_signal_from_features("NIFTY", current, previous)
        self.assertEqual(result.signal.value, "Wait")
        self.assertIn("persisted", result.reason)

    def test_waits_in_rangebound_state(self) -> None:
        current = (
            _feature("5m", price_rangebound=True, rangebound_oi_both_sides=True, breakout_flag=False, volume_spike=False),
            _feature("30m", price_rangebound=True, rangebound_oi_both_sides=True, breakout_flag=False, volume_spike=False),
            _feature("60m", price_rangebound=True, rangebound_oi_both_sides=True, breakout_flag=False, volume_spike=False),
        )
        result = generate_main_signal_from_features("NIFTY", current, None)
        self.assertEqual(result.signal.value, "Wait")
        self.assertIn("rangebound", result.reason.lower())


if __name__ == "__main__":
    unittest.main()
