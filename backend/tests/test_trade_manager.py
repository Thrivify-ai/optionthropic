import unittest
from datetime import datetime, timezone

from app.analytics.trade_manager import (
    OpenTradeState,
    derive_managed_trade_decision,
    result_label_from_points,
)


class TradeManagerTests(unittest.TestCase):
    def test_entry_decision_opens_new_trade(self) -> None:
        decision = derive_managed_trade_decision(
            engine="QUICK",
            symbol="NIFTY",
            previous_trade=None,
            base_signal="Buy CE",
            confidence=82,
            current_price=23300.0,
            reason="Fresh bullish impulse confirmed.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Buy CE")
        self.assertEqual(decision.trade_state, "entry")
        self.assertEqual(decision.current_points, 0.0)
        self.assertEqual(decision.success_threshold_points, 10.0)

    def test_hold_decision_ignores_noise_after_entry(self) -> None:
        previous = OpenTradeState(
            id=1,
            engine="QUICK",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=82,
            success_threshold_points=10.0,
            stop_points=8.0,
            hold_cycles=1,
            max_favorable_points=3.0,
            max_adverse_points=-1.0,
        )
        decision = derive_managed_trade_decision(
            engine="QUICK",
            symbol="NIFTY",
            previous_trade=previous,
            base_signal="Wait",
            confidence=38,
            current_price=23304.0,
            reason="No fresh entry, but structure is not invalidated.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Hold CE")
        self.assertEqual(decision.trade_state, "hold")
        self.assertEqual(decision.current_points, 4.0)

    def test_exit_decision_books_profit_after_threshold_when_signal_fades(self) -> None:
        previous = OpenTradeState(
            id=1,
            engine="QUICK",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=82,
            success_threshold_points=10.0,
            stop_points=8.0,
            hold_cycles=2,
            max_favorable_points=8.0,
            max_adverse_points=-1.0,
        )
        decision = derive_managed_trade_decision(
            engine="QUICK",
            symbol="NIFTY",
            previous_trade=previous,
            base_signal="Wait",
            confidence=72,
            current_price=23312.0,
            reason="Momentum is fading after a clean move.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Exit CE")
        self.assertEqual(decision.trade_state, "exit")
        self.assertEqual(decision.current_points, 12.0)

    def test_exit_decision_triggers_on_high_confidence_opposite_signal(self) -> None:
        previous = OpenTradeState(
            id=1,
            engine="MAIN",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=79,
            success_threshold_points=20.0,
            stop_points=14.0,
            hold_cycles=3,
            max_favorable_points=18.0,
            max_adverse_points=-4.0,
        )
        decision = derive_managed_trade_decision(
            engine="MAIN",
            symbol="NIFTY",
            previous_trade=previous,
            base_signal="Buy PE",
            confidence=78,
            current_price=23290.0,
            reason="30m and 60m structure have flipped bearish.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Exit CE")
        self.assertEqual(decision.trade_state, "exit")
        self.assertLess(decision.current_points, 0)

    def test_result_label_uses_success_threshold(self) -> None:
        self.assertEqual(result_label_from_points(12.0, success_threshold=10.0), "Won")
        self.assertEqual(result_label_from_points(5.0, success_threshold=10.0), "Scratch")
        self.assertEqual(result_label_from_points(-3.0, success_threshold=10.0), "Lost")


if __name__ == "__main__":
    unittest.main()
