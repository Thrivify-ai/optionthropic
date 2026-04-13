import unittest
from datetime import datetime, timezone

from app.analytics.trade_manager import (
    OpenTradeState,
    derive_managed_trade_decision,
    direction_for_signal,
    points_for_direction,
    result_label_from_points,
)


class TradeManagerTests(unittest.TestCase):
    def test_entry_decision_opens_new_trade(self) -> None:
        decision = derive_managed_trade_decision(
            engine="QUICK",
            symbol="NIFTY",
            previous_trade=None,
            base_signal="Buy CE",
            confidence=88,
            current_price=23300.0,
            reason="Fresh bullish impulse confirmed.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Buy CE")
        self.assertEqual(decision.trade_state, "entry")
        self.assertEqual(decision.current_points, 0.0)
        self.assertEqual(decision.success_threshold_points, 10.0)

    def test_entry_decision_blocks_low_confidence(self) -> None:
        decision = derive_managed_trade_decision(
            engine="QUICK",
            symbol="NIFTY",
            previous_trade=None,
            base_signal="Buy CE",
            confidence=74,
            current_price=23300.0,
            reason="Weak impulse.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Wait")
        self.assertEqual(decision.trade_state, "idle")
        self.assertIn("below", decision.management_reason.lower())

    def test_entry_decision_respects_reentry_lockout(self) -> None:
        decision = derive_managed_trade_decision(
            engine="QUICK",
            symbol="NIFTY",
            previous_trade=None,
            base_signal="Buy CE",
            confidence=92,
            current_price=23300.0,
            reason="Fresh bullish impulse confirmed.",
            hard_exit=False,
            reentry_block_reason="Re-entry lockout active for CE: wait 60s.",
        )
        self.assertEqual(decision.public_signal, "Wait")
        self.assertEqual(decision.trade_state, "idle")
        self.assertIn("lockout", decision.management_reason.lower())

    def test_entry_decision_respects_external_entry_gate(self) -> None:
        decision = derive_managed_trade_decision(
            engine="MAIN",
            symbol="NIFTY",
            previous_trade=None,
            base_signal="Buy CE",
            confidence=91,
            current_price=23300.0,
            reason="Setup ready.",
            hard_exit=False,
            entry_gate_reason="Entry blocked: midday structure is still noisy for fresh long entries.",
        )
        self.assertEqual(decision.public_signal, "Wait")
        self.assertEqual(decision.trade_state, "idle")
        self.assertIn("blocked", decision.management_reason.lower())

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

    def test_exit_decision_protects_partial_profit_when_followthrough_fades(self) -> None:
        previous = OpenTradeState(
            id=1,
            engine="QUICK",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=90,
            success_threshold_points=10.0,
            stop_points=8.0,
            hold_cycles=2,
            max_favorable_points=9.0,
            max_adverse_points=-1.0,
        )
        decision = derive_managed_trade_decision(
            engine="QUICK",
            symbol="NIFTY",
            previous_trade=previous,
            base_signal="Wait",
            confidence=54,
            current_price=23308.0,
            reason="Momentum cooled after the initial burst.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Exit CE")
        self.assertEqual(decision.trade_state, "exit")
        self.assertIn("partial profit", decision.management_reason.lower())

    def test_exit_decision_uses_trailing_protection_after_giveback(self) -> None:
        previous = OpenTradeState(
            id=1,
            engine="QUICK",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=92,
            success_threshold_points=10.0,
            stop_points=8.0,
            hold_cycles=3,
            max_favorable_points=16.0,
            max_adverse_points=-1.0,
        )
        decision = derive_managed_trade_decision(
            engine="QUICK",
            symbol="NIFTY",
            previous_trade=previous,
            base_signal="Buy CE",
            confidence=82,
            current_price=23309.0,
            reason="Still bullish but giving back gains.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Exit CE")
        self.assertEqual(decision.trade_state, "exit")
        self.assertIn("trailing protection", decision.management_reason.lower())

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

    def test_opposite_signal_needs_persistence_for_recent_quick_trade(self) -> None:
        previous = OpenTradeState(
            id=1,
            engine="QUICK",
            symbol="NIFTY",
            direction="CE",
            entry_signal="Buy CE",
            entry_price=23300.0,
            entry_time=datetime(2026, 3, 25, 4, 30, tzinfo=timezone.utc),
            entry_confidence=90,
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
            base_signal="Buy PE",
            confidence=92,
            current_price=23298.0,
            reason="Quick opposite impulse appeared.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "Hold CE")
        self.assertEqual(decision.trade_state, "hold")
        self.assertIn("one more cycle", decision.management_reason.lower())

    def test_result_label_uses_success_threshold(self) -> None:
        self.assertEqual(result_label_from_points(12.0, success_threshold=10.0), "Won")
        self.assertEqual(result_label_from_points(5.0, success_threshold=10.0), "Scratch")
        self.assertEqual(result_label_from_points(-3.0, success_threshold=10.0), "Lost")

    def test_commodity_long_entry_uses_futures_thresholds(self) -> None:
        decision = derive_managed_trade_decision(
            engine="COMMODITY_QUICK",
            symbol="CRUDEOIL",
            previous_trade=None,
            base_signal="LONG",
            confidence=82,
            current_price=6100.0,
            reason="Clean upside commodity burst.",
            hard_exit=False,
        )
        self.assertEqual(decision.public_signal, "LONG")
        self.assertEqual(decision.direction, "LONG")
        self.assertEqual(decision.success_threshold_points, 20.0)
        self.assertEqual(decision.stop_points, 14.0)

    def test_commodity_short_points_are_directional(self) -> None:
        self.assertEqual(direction_for_signal("SHORT"), "SHRT")
        self.assertEqual(points_for_direction("SHRT", 6100.0, 6084.0), 16.0)
        self.assertEqual(points_for_direction("LONG", 6100.0, 6116.0), 16.0)


if __name__ == "__main__":
    unittest.main()
