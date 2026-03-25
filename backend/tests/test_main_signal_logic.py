import unittest

from app.analytics.main_signal_logic import (
    FeatureView,
    derive_signal_context,
    generate_main_signal_from_features,
)
from app.analytics.main_signal_runtime import LongSignalContext


def _feature(
    timeframe: str,
    *,
    current_price: float = 100.0,
    prev_price: float = 99.0,
    price_change_pct: float | None = None,
    pcr_oi: float | None = 1.2,
    support_strike: float = 95.0,
    resistance_strike: float = 105.0,
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
        price_change_pct=price_change_pct if price_change_pct is not None else ((current_price - prev_price) / prev_price),
        pcr_oi=pcr_oi,
        support_strike=support_strike,
        resistance_strike=resistance_strike,
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
        data_quality_score=100,
    )


def _context(
    *,
    session_vwap: float | None = 100.0,
    opening_range_high: float | None = 101.0,
    opening_range_low: float | None = 99.0,
    previous_day_high: float | None = 100.5,
    previous_day_low: float | None = 97.5,
    previous_day_close: float | None = 99.8,
    session_bucket: str | None = "MIDDAY",
    news_impact_score: int = 0,
    event_profile: str = "normal",
    days_to_expiry: int | None = 3,
    expiry_bucket: str | None = "2_5DTE",
    is_expiry_day: bool = False,
) -> LongSignalContext:
    return LongSignalContext(
        session_vwap=session_vwap,
        opening_range_high=opening_range_high,
        opening_range_low=opening_range_low,
        previous_day_high=previous_day_high,
        previous_day_low=previous_day_low,
        previous_day_close=previous_day_close,
        session_bucket=session_bucket,
        news_impact_score=news_impact_score,
        event_profile=event_profile,
        days_to_expiry=days_to_expiry,
        expiry_bucket=expiry_bucket,
        is_expiry_day=is_expiry_day,
    )


class MainSignalLogicTests(unittest.TestCase):
    def test_emits_buy_ce_when_aligned_and_persistent(self) -> None:
        current = (
            _feature("5m", current_price=102.0, prev_price=100.0, resistance_strike=130.0, breakout_flag=True),
            _feature("30m", current_price=104.0, prev_price=100.0, resistance_strike=132.0, breakout_flag=True),
            _feature("60m", current_price=108.0, prev_price=100.0, resistance_strike=138.0, breakout_flag=True),
        )
        previous = (
            _feature("5m", current_price=101.0, prev_price=99.0, resistance_strike=129.0, breakout_flag=True),
            _feature("30m", current_price=103.0, prev_price=99.0, resistance_strike=131.0, breakout_flag=True),
            _feature("60m", current_price=107.0, prev_price=99.0, resistance_strike=137.0, breakout_flag=True),
        )
        result = generate_main_signal_from_features("NIFTY", current, previous, context=_context())
        self.assertEqual(result.signal.value, "Buy CE")
        self.assertGreaterEqual(result.confidence, 70)

    def test_waits_with_bullish_outlook_when_entry_not_ready(self) -> None:
        current = (
            _feature("5m", current_price=100.2, prev_price=100.0, pcr_oi=1.02, writer_bullish_score=0, breakout_flag=False, volume_spike=False, position_buildup=None),
            _feature("30m", current_price=103.0, prev_price=100.0, breakout_flag=True),
            _feature("60m", current_price=106.0, prev_price=100.0, breakout_flag=True),
        )
        previous = (
            _feature("5m", current_price=100.1, prev_price=100.0, pcr_oi=1.01, writer_bullish_score=0, breakout_flag=False, volume_spike=False, position_buildup=None),
            _feature("30m", current_price=102.8, prev_price=99.8, breakout_flag=True),
            _feature("60m", current_price=105.8, prev_price=99.8, breakout_flag=True),
        )
        result = generate_main_signal_from_features("NIFTY", current, previous, context=_context())
        self.assertEqual(result.signal.value, "Wait")
        self.assertGreater(result.confidence, 0)
        self.assertIn("finish bias", result.reason.lower())
        self.assertIn("timing", result.reason.lower())

    def test_waits_when_alignment_has_not_persisted(self) -> None:
        current = (_feature("5m"), _feature("30m"), _feature("60m"))
        previous = (
            _feature("5m", current_price=99.0, prev_price=100.0, pcr_oi=0.8, writer_bullish_score=0, writer_bearish_score=1, position_buildup="Short buildup", breakout_flag=False, breakdown_flag=True),
            _feature("30m", current_price=99.0, prev_price=100.0, pcr_oi=0.8, writer_bullish_score=0, writer_bearish_score=1, position_buildup="Short buildup", breakout_flag=False, breakdown_flag=True),
            _feature("60m", current_price=99.0, prev_price=100.0, pcr_oi=0.8, writer_bullish_score=0, writer_bearish_score=1, position_buildup="Short buildup", breakout_flag=False, breakdown_flag=True),
        )
        result = generate_main_signal_from_features("NIFTY", current, previous, context=_context())
        self.assertEqual(result.signal.value, "Wait")
        self.assertIn("persisted", result.reason)

    def test_waits_in_rangebound_state(self) -> None:
        current = (
            _feature("5m", price_rangebound=True, rangebound_oi_both_sides=True, breakout_flag=False, volume_spike=False),
            _feature("30m", price_rangebound=True, rangebound_oi_both_sides=True, breakout_flag=False, volume_spike=False),
            _feature("60m", price_rangebound=True, rangebound_oi_both_sides=True, breakout_flag=False, volume_spike=False),
        )
        result = generate_main_signal_from_features("NIFTY", current, None, context=_context())
        self.assertEqual(result.signal.value, "Wait")
        self.assertIn("rangebound", result.reason.lower())

    def test_waits_when_bullish_options_bias_is_back_below_vwap(self) -> None:
        current = (
            _feature("5m", current_price=100.4, prev_price=100.0, breakout_flag=False, volume_spike=False),
            _feature("30m", current_price=103.0, prev_price=100.0, breakout_flag=True),
            _feature("60m", current_price=106.0, prev_price=100.0, breakout_flag=True),
        )
        previous = (
            _feature("5m", current_price=100.2, prev_price=99.9, breakout_flag=False, volume_spike=False),
            _feature("30m", current_price=102.5, prev_price=99.5, breakout_flag=True),
            _feature("60m", current_price=105.5, prev_price=99.5, breakout_flag=True),
        )
        result = generate_main_signal_from_features(
            "NIFTY",
            current,
            previous,
            context=_context(session_vwap=101.8, opening_range_high=102.2, opening_range_low=100.1),
        )
        self.assertEqual(result.signal.value, "Wait")
        self.assertIn("wrong side of session vwap", result.reason.lower())

    def test_expiry_day_requires_clean_break_for_entry(self) -> None:
        current = (
            _feature("5m", current_price=101.1, prev_price=100.6, breakout_flag=False, volume_spike=True),
            _feature("30m", current_price=103.0, prev_price=100.0, breakout_flag=True),
            _feature("60m", current_price=106.0, prev_price=100.0, breakout_flag=True),
        )
        previous = (
            _feature("5m", current_price=101.0, prev_price=100.5, breakout_flag=False, volume_spike=True),
            _feature("30m", current_price=102.8, prev_price=99.8, breakout_flag=True),
            _feature("60m", current_price=105.8, prev_price=99.8, breakout_flag=True),
        )
        result = generate_main_signal_from_features(
            "NIFTY",
            current,
            previous,
            context=_context(
                session_vwap=100.9,
                opening_range_high=101.6,
                opening_range_low=99.8,
                previous_day_high=102.0,
                event_profile="expiry",
                days_to_expiry=0,
                expiry_bucket="0DTE",
                is_expiry_day=True,
                session_bucket="CLOSING",
            ),
        )
        self.assertEqual(result.signal.value, "Wait")
        self.assertIn("finish bias", result.reason.lower())

    def test_derive_signal_context_reports_setup_for_higher_timeframe_alignment(self) -> None:
        ctx = derive_signal_context("Wait", "Neutral", "Bullish", "Bullish", 58)
        self.assertEqual(ctx["outlook"], "Bullish")
        self.assertEqual(ctx["state"], "setup")
        self.assertFalse(ctx["entry_ready"])

    def test_derive_signal_context_marks_hold_as_active(self) -> None:
        ctx = derive_signal_context("Hold CE", "Bullish", "Bullish", "Bullish", 74)
        self.assertEqual(ctx["outlook"], "Bullish")
        self.assertEqual(ctx["state"], "active")
        self.assertTrue(ctx["entry_ready"])

    def test_derive_signal_context_marks_exit_state(self) -> None:
        ctx = derive_signal_context("Exit PE", "Bearish", "Bearish", "Bearish", 71)
        self.assertEqual(ctx["outlook"], "Bearish")
        self.assertEqual(ctx["state"], "exit")
        self.assertFalse(ctx["entry_ready"])


if __name__ == "__main__":
    unittest.main()
