import unittest
from datetime import datetime, timedelta, timezone

from app.analytics.quick_signal_phase2 import (
    QuickSignalLifecycleState,
    apply_lifecycle,
    quick_signal_confidence,
    reward_risk_ok,
    session_profile_for,
)


class QuickSignalPhase2Tests(unittest.TestCase):
    def test_session_profiles_change_by_market_window(self) -> None:
        opening = session_profile_for(datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc))
        midday = session_profile_for(datetime(2026, 3, 20, 7, 30, tzinfo=timezone.utc))
        weekend = session_profile_for(datetime(2026, 3, 21, 6, 0, tzinfo=timezone.utc))

        self.assertEqual(opening.name, "opening")
        self.assertEqual(midday.name, "midday")
        self.assertEqual(weekend.name, "closed")
        self.assertGreater(midday.min_confidence, opening.min_confidence)

    def test_reward_risk_requires_headroom_before_level(self) -> None:
        ok, reason = reward_risk_ok(
            "Buy CE",
            spot=22100.0,
            support=22040.0,
            resistance=22140.0,
            target_move=35.0,
            breakout=False,
            breakdown=False,
        )
        bad, bad_reason = reward_risk_ok(
            "Buy CE",
            spot=22128.0,
            support=22040.0,
            resistance=22140.0,
            target_move=35.0,
            breakout=False,
            breakdown=False,
        )

        self.assertTrue(ok)
        self.assertIn("headroom", reason.lower())
        self.assertFalse(bad)
        self.assertIn("only", bad_reason.lower())

    def test_confidence_penalizes_traps_and_range(self) -> None:
        clean = quick_signal_confidence(
            bullish=True,
            bearish=False,
            strong_1m=True,
            strong_3m=True,
            breakout=True,
            breakdown=False,
            volume_spike=True,
            oi_confirmed=True,
            persistent=True,
            trap=False,
            rangebound=False,
            risk_reward_ok=True,
        )
        noisy = quick_signal_confidence(
            bullish=True,
            bearish=False,
            strong_1m=True,
            strong_3m=False,
            breakout=False,
            breakdown=False,
            volume_spike=False,
            oi_confirmed=False,
            persistent=False,
            trap=True,
            rangebound=True,
            risk_reward_ok=False,
        )

        self.assertGreater(clean, noisy)
        self.assertGreaterEqual(clean, 70)
        self.assertEqual(noisy, 0)

    def test_lifecycle_promotes_candidate_to_active(self) -> None:
        profile = session_profile_for(datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc))
        state = QuickSignalLifecycleState()
        now_utc = datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc)

        state, payload = apply_lifecycle(
            state,
            raw_signal="Buy CE",
            confidence=82,
            now_utc=now_utc,
            profile=profile,
            hard_invalidation=False,
        )
        self.assertEqual(payload["quick_signal"], "Wait")
        self.assertEqual(payload["state"], "candidate")
        self.assertEqual(payload["stability_cycles"], 1)

        state, payload = apply_lifecycle(
            state,
            raw_signal="Buy CE",
            confidence=84,
            now_utc=now_utc + timedelta(seconds=15),
            profile=profile,
            hard_invalidation=False,
        )
        self.assertEqual(payload["quick_signal"], "Buy CE")
        self.assertEqual(payload["state"], "active")
        self.assertEqual(state.active_signal, "Buy CE")

    def test_lifecycle_holds_active_signal_through_brief_pause(self) -> None:
        profile = session_profile_for(datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc))
        now_utc = datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc)
        state = QuickSignalLifecycleState(
            state="active",
            candidate_signal="Buy CE",
            candidate_count=profile.confirm_cycles,
            active_signal="Buy CE",
            activated_at=now_utc.isoformat(),
            last_seen_at=now_utc.isoformat(),
            confidence=83,
        )

        state, payload = apply_lifecycle(
            state,
            raw_signal="Wait",
            confidence=40,
            now_utc=now_utc + timedelta(seconds=30),
            profile=profile,
            hard_invalidation=False,
        )
        self.assertEqual(payload["quick_signal"], "Buy CE")
        self.assertEqual(payload["state"], "active")
        self.assertIn("minimum hold window", payload["state_reason"])

    def test_lifecycle_moves_to_cooldown_after_hold_window(self) -> None:
        profile = session_profile_for(datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc))
        now_utc = datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc)
        activated_at = now_utc - timedelta(seconds=profile.min_hold_seconds + 5)
        state = QuickSignalLifecycleState(
            state="active",
            candidate_signal="Buy CE",
            candidate_count=profile.confirm_cycles,
            active_signal="Buy CE",
            activated_at=activated_at.isoformat(),
            last_seen_at=activated_at.isoformat(),
            confidence=83,
        )

        state, payload = apply_lifecycle(
            state,
            raw_signal="Wait",
            confidence=35,
            now_utc=now_utc,
            profile=profile,
            hard_invalidation=False,
        )
        self.assertEqual(payload["quick_signal"], "Wait")
        self.assertEqual(payload["state"], "cooldown")
        self.assertGreater(payload["cooldown_seconds_remaining"], 0)

    def test_hard_invalidation_forces_immediate_cooldown(self) -> None:
        profile = session_profile_for(datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc))
        now_utc = datetime(2026, 3, 20, 4, 5, tzinfo=timezone.utc)
        state = QuickSignalLifecycleState(
            state="active",
            candidate_signal="Buy PE",
            candidate_count=profile.confirm_cycles,
            active_signal="Buy PE",
            activated_at=(now_utc - timedelta(seconds=20)).isoformat(),
            last_seen_at=(now_utc - timedelta(seconds=20)).isoformat(),
            confidence=81,
        )

        state, payload = apply_lifecycle(
            state,
            raw_signal="Wait",
            confidence=10,
            now_utc=now_utc,
            profile=profile,
            hard_invalidation=True,
        )
        self.assertEqual(payload["quick_signal"], "Wait")
        self.assertEqual(payload["state"], "cooldown")
        self.assertIn("invalidated", payload["state_reason"].lower())


if __name__ == "__main__":
    unittest.main()
