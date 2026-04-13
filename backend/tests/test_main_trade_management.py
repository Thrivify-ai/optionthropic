import unittest
from datetime import datetime, timezone

from app.analytics.main_signal_logic import FeatureView
from app.analytics.main_signal_runtime import LongSignalContext
from app.analytics.main_trade_management import derive_main_trade_management_plan
from app.analytics.signal_engine import Bias
from app.analytics.trade_manager import OpenTradeState


def _feature(
    timeframe: str,
    *,
    current_price: float,
    prev_price: float,
    breakout_flag: bool = False,
    breakdown_flag: bool = False,
    trap_warning_flag: bool = False,
) -> FeatureView:
    return FeatureView(
        timeframe=timeframe,
        current_price=current_price,
        prev_price=prev_price,
        price_change_pct=((current_price - prev_price) / prev_price) if prev_price else 0.0,
        pcr_oi=1.1,
        support_strike=98.0,
        resistance_strike=105.0,
        near_support_put_oi_change=10,
        near_resistance_call_oi_change=-3,
        writer_bullish_score=1,
        writer_bearish_score=0,
        position_buildup="Long buildup",
        volume_spike=True,
        price_rangebound=False,
        rangebound_oi_both_sides=False,
        breakout_flag=breakout_flag,
        breakdown_flag=breakdown_flag,
        trap_warning_flag=trap_warning_flag,
        data_quality_score=100,
    )


class MainTradeManagementTests(unittest.TestCase):
    def test_bullish_finish_bias_keeps_long_trade_in_hold_mode(self) -> None:
        open_trade = OpenTradeState(
            id=1,
            engine="MAIN",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=80,
            success_threshold_points=20.0,
            stop_points=14.0,
            hold_cycles=2,
            max_favorable_points=18.0,
            max_adverse_points=-4.0,
        )
        context = LongSignalContext(
            session_vwap=23312.0,
            opening_range_high=23320.0,
            opening_range_low=23288.0,
            previous_day_high=23318.0,
            previous_day_low=23240.0,
            previous_day_close=23296.0,
            session_bucket="MIDDAY",
            event_profile="normal",
        )
        plan = derive_main_trade_management_plan(
            open_trade=open_trade,
            current_features=(
                _feature("5m", current_price=23324.0, prev_price=23315.0, breakout_flag=False),
                _feature("30m", current_price=23324.0, prev_price=23300.0, breakout_flag=True),
                _feature("60m", current_price=23324.0, prev_price=23270.0, breakout_flag=True),
            ),
            long_context=context,
            outlook=Bias.BULLISH,
            confidence=74,
            current_price=23324.0,
        )
        self.assertEqual(plan.base_signal_override, "Buy CE")
        self.assertFalse(plan.hard_exit)

    def test_break_below_vwap_and_session_support_forces_exit(self) -> None:
        open_trade = OpenTradeState(
            id=1,
            engine="MAIN",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=80,
            success_threshold_points=20.0,
            stop_points=14.0,
            hold_cycles=4,
            max_favorable_points=24.0,
            max_adverse_points=-4.0,
        )
        context = LongSignalContext(
            session_vwap=23308.0,
            opening_range_high=23322.0,
            opening_range_low=23292.0,
            previous_day_high=23318.0,
            previous_day_low=23270.0,
            previous_day_close=23298.0,
            session_bucket="CLOSING",
            event_profile="normal",
        )
        plan = derive_main_trade_management_plan(
            open_trade=open_trade,
            current_features=(
                _feature("5m", current_price=23286.0, prev_price=23302.0, breakdown_flag=True),
                _feature("30m", current_price=23286.0, prev_price=23318.0, breakdown_flag=True),
                _feature("60m", current_price=23286.0, prev_price=23330.0, breakdown_flag=True),
            ),
            long_context=context,
            outlook=Bias.NEUTRAL,
            confidence=58,
            current_price=23286.0,
        )
        self.assertTrue(plan.hard_exit)
        self.assertIn("VWAP", plan.hard_exit_reason)

    def test_breadth_flip_forces_exit_on_weak_long_trade(self) -> None:
        open_trade = OpenTradeState(
            id=1,
            engine="MAIN",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=82,
            success_threshold_points=20.0,
            stop_points=14.0,
            hold_cycles=2,
            max_favorable_points=11.0,
            max_adverse_points=-4.0,
        )
        context = LongSignalContext(
            session_vwap=23304.0,
            opening_range_high=23318.0,
            opening_range_low=23290.0,
            previous_day_high=23322.0,
            previous_day_low=23270.0,
            previous_day_close=23296.0,
            session_bucket="MIDDAY",
            event_profile="normal",
            breadth_available=True,
            breadth_score=-30,
            breadth_direction="bearish",
        )
        plan = derive_main_trade_management_plan(
            open_trade=open_trade,
            current_features=(
                _feature("5m", current_price=23306.0, prev_price=23300.0),
                _feature("30m", current_price=23308.0, prev_price=23296.0),
                _feature("60m", current_price=23310.0, prev_price=23280.0),
            ),
            long_context=context,
            outlook=Bias.BULLISH,
            confidence=68,
            current_price=23306.0,
        )
        self.assertTrue(plan.hard_exit)
        self.assertIn("breadth", plan.hard_exit_reason.lower())


if __name__ == "__main__":
    unittest.main()
