"""
Phase 2 helpers for quick-signal quality and lifecycle management.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any


BUY_SIGNALS = {"Buy CE", "Buy PE"}


@dataclass
class QuickSignalSessionProfile:
    name: str
    threshold_multiplier: float
    min_confidence: int
    min_confirmation_count: int
    confirm_cycles: int
    min_hold_seconds: int
    cooldown_seconds: int
    allow_soft_entries: bool = False
    requires_breakout: bool = False
    min_breadth_score: int = 0


@dataclass
class QuickSignalLifecycleState:
    state: str = "idle"
    candidate_signal: str | None = None
    candidate_count: int = 0
    active_signal: str | None = None
    activated_at: str | None = None
    last_seen_at: str | None = None
    cooldown_until: str | None = None
    confidence: int = 0
    last_data_key: str | None = None
    reversal_signal: str | None = None
    reversal_count: int = 0
    reversal_last_seen_at: str | None = None


def session_profile_for(now_utc: datetime | None = None) -> QuickSignalSessionProfile:
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    now_ist = current.astimezone(timezone(timedelta(hours=5, minutes=30)))

    if now_ist.weekday() > 4:
        return QuickSignalSessionProfile("closed", 1.35, 90, 5, 99, 0, 0, False, True, 40)

    t = now_ist.time()
    if dtime(9, 15) <= t < dtime(10, 30):
        return QuickSignalSessionProfile("opening", 1.04, 83, 4, 2, 90, 60, True, False, 14)
    if dtime(10, 30) <= t < dtime(13, 45):
        return QuickSignalSessionProfile("midday", 1.30, 90, 5, 2, 120, 90, False, True, 24)
    if dtime(13, 45) <= t <= dtime(15, 30):
        return QuickSignalSessionProfile("closing", 1.08, 84, 4, 2, 90, 60, True, False, 12)
    return QuickSignalSessionProfile("closed", 1.35, 90, 5, 99, 0, 0, False, True, 40)


def adjusted_threshold(value: float, profile: QuickSignalSessionProfile) -> float:
    return round(value * profile.threshold_multiplier, 2)


def reward_risk_ok(
    signal: str,
    *,
    spot: float,
    support: float | None,
    resistance: float | None,
    target_move: float,
    breakout: bool,
    breakdown: bool,
) -> tuple[bool, str]:
    required_headroom = max(target_move * 0.5, spot * 0.0015)
    allowed_extension = max(target_move * 0.25, spot * 0.0006)
    if signal == "Buy CE":
        if breakout:
            if resistance is None:
                return True, "Breakout cleared the prior resistance"
            extension = spot - resistance
            if extension <= allowed_extension:
                return True, f"Breakout is still within {extension:.0f} pts of resistance"
            return False, f"Breakout is already extended {extension:.0f} pts above resistance"
        if resistance is None:
            return True, "No nearby resistance wall"
        headroom = resistance - spot
        if headroom >= required_headroom:
            return True, f"Upside headroom {headroom:.0f} pts"
        return False, f"Upside headroom only {headroom:.0f} pts before resistance"

    if signal == "Buy PE":
        if breakdown:
            if support is None:
                return True, "Breakdown cleared the prior support"
            extension = support - spot
            if extension <= allowed_extension:
                return True, f"Breakdown is still within {extension:.0f} pts of support"
            return False, f"Breakdown is already extended {extension:.0f} pts below support"
        if support is None:
            return True, "No nearby support wall"
        headroom = spot - support
        if headroom >= required_headroom:
            return True, f"Downside headroom {headroom:.0f} pts"
        return False, f"Downside headroom only {headroom:.0f} pts before support"

    return False, "No trade direction"


def quick_signal_confidence(
    *,
    bullish: bool,
    bearish: bool,
    strong_1m: bool,
    strong_3m: bool,
    breakout: bool,
    breakdown: bool,
    volume_spike: bool,
    oi_confirmed: bool,
    persistent: bool,
    confirmation_count: int,
    fresh_data: bool,
    trap: bool,
    rangebound: bool,
    risk_reward_ok: bool,
    breadth_aligned: bool,
    breadth_score: int,
    short_covering_risk: int,
    volatility_ratio: float | None,
    session_name: str,
    regime_blocked: bool = False,
) -> int:
    if not bullish and not bearish:
        return 0

    score = 0
    if strong_1m:
        score += 28
    if strong_3m:
        score += 18
    if breakout or breakdown:
        score += 15
    if volume_spike:
        score += 10
    if oi_confirmed:
        score += 12
    if persistent:
        score += 14
    if risk_reward_ok:
        score += 12
    if breadth_aligned:
        score += 10
    score += min(8, max(0, int(abs(breadth_score) / 8)))
    score += min(max(confirmation_count, 0), 4) * 4
    if fresh_data:
        score += 4
    if volatility_ratio is not None:
        if 0.9 <= volatility_ratio <= 1.85:
            score += 6
        elif volatility_ratio < 0.75:
            score -= 8

    if trap:
        score -= 38
    if rangebound:
        score -= 28
    if not risk_reward_ok:
        score -= 18
    if not breadth_aligned and breadth_score != 0:
        score -= 16
    if short_covering_risk >= 70:
        score -= 24
    elif short_covering_risk >= 50:
        score -= 12
    if confirmation_count < 2:
        score -= 16
    if not fresh_data:
        score -= 8
    if session_name == "midday":
        score -= 8
    if regime_blocked:
        score -= 24

    return max(0, min(100, score))


def parse_lifecycle_state(payload: dict[str, Any] | None) -> QuickSignalLifecycleState:
    if not payload:
        return QuickSignalLifecycleState()
    return QuickSignalLifecycleState(
        state=payload.get("state", "idle"),
        candidate_signal=payload.get("candidate_signal"),
        candidate_count=int(payload.get("candidate_count", 0) or 0),
        active_signal=payload.get("active_signal"),
        activated_at=payload.get("activated_at"),
        last_seen_at=payload.get("last_seen_at"),
        cooldown_until=payload.get("cooldown_until"),
        confidence=int(payload.get("confidence", 0) or 0),
        last_data_key=payload.get("last_data_key"),
        reversal_signal=payload.get("reversal_signal"),
        reversal_count=int(payload.get("reversal_count", 0) or 0),
        reversal_last_seen_at=payload.get("reversal_last_seen_at"),
    )


def serialize_lifecycle_state(state: QuickSignalLifecycleState) -> dict[str, Any]:
    return asdict(state)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def apply_lifecycle(
    previous: QuickSignalLifecycleState,
    *,
    raw_signal: str,
    confidence: int,
    now_utc: datetime,
    profile: QuickSignalSessionProfile,
    hard_invalidation: bool,
    data_key: str | None = None,
    fast_track: bool = False,
) -> tuple[QuickSignalLifecycleState, dict[str, Any]]:
    now_iso = now_utc.isoformat()
    state = QuickSignalLifecycleState(
        state=previous.state,
        candidate_signal=previous.candidate_signal,
        candidate_count=previous.candidate_count,
        active_signal=previous.active_signal,
        activated_at=previous.activated_at,
        last_seen_at=previous.last_seen_at,
        cooldown_until=previous.cooldown_until,
        confidence=previous.confidence,
        last_data_key=previous.last_data_key,
        reversal_signal=previous.reversal_signal,
        reversal_count=previous.reversal_count,
        reversal_last_seen_at=previous.reversal_last_seen_at,
    )

    activated_at = _parse_ts(state.activated_at)
    cooldown_until = _parse_ts(state.cooldown_until)
    active_age = int((now_utc - activated_at).total_seconds()) if activated_at else 0
    cooldown_remaining = int((cooldown_until - now_utc).total_seconds()) if cooldown_until and cooldown_until > now_utc else 0
    required_cycles = 1 if fast_track else profile.confirm_cycles

    if hard_invalidation and state.active_signal:
        state.state = "cooldown"
        state.candidate_signal = None
        state.candidate_count = 0
        state.active_signal = None
        state.reversal_signal = None
        state.reversal_count = 0
        state.reversal_last_seen_at = None
        state.cooldown_until = (now_utc + timedelta(seconds=profile.cooldown_seconds)).isoformat()
        state.confidence = confidence
        state.last_data_key = data_key
        return state, {
            "quick_signal": "Wait",
            "state": "cooldown",
            "stability_cycles": 0,
            "active_age_seconds": active_age,
            "cooldown_seconds_remaining": profile.cooldown_seconds,
            "state_reason": "Previous active signal invalidated by trap or regime breakdown.",
        }

    if cooldown_remaining > 0:
        state.state = "cooldown"
        state.active_signal = None
        state.candidate_signal = None
        state.candidate_count = 0
        state.reversal_signal = None
        state.reversal_count = 0
        state.reversal_last_seen_at = None
        state.confidence = confidence
        state.last_data_key = data_key
        return state, {
            "quick_signal": "Wait",
            "state": "cooldown",
            "stability_cycles": 0,
            "active_age_seconds": 0,
            "cooldown_seconds_remaining": cooldown_remaining,
            "state_reason": "Cooling down after the previous quick signal.",
        }

    if state.active_signal in BUY_SIGNALS:
        if raw_signal == state.active_signal:
            state.state = "active"
            state.last_seen_at = now_iso
            state.confidence = confidence
            state.last_data_key = data_key or state.last_data_key
            state.reversal_signal = None
            state.reversal_count = 0
            state.reversal_last_seen_at = None
            return state, {
                "quick_signal": state.active_signal,
                "state": "active",
                "stability_cycles": max(required_cycles, state.candidate_count),
                "active_age_seconds": active_age,
                "cooldown_seconds_remaining": 0,
                "state_reason": "Active signal remains aligned and confirmed.",
            }

        if raw_signal == "Wait" and active_age < profile.min_hold_seconds:
            state.state = "active"
            state.confidence = max(state.confidence, confidence)
            state.last_data_key = data_key or state.last_data_key
            state.reversal_signal = None
            state.reversal_count = 0
            state.reversal_last_seen_at = None
            return state, {
                "quick_signal": state.active_signal,
                "state": "active",
                "stability_cycles": max(required_cycles, state.candidate_count),
                "active_age_seconds": active_age,
                "cooldown_seconds_remaining": 0,
                "state_reason": "Holding the active signal through a brief pause inside the minimum hold window.",
            }

        if raw_signal in BUY_SIGNALS and raw_signal != state.active_signal and active_age < profile.min_hold_seconds:
            state.state = "active"
            state.last_data_key = data_key or state.last_data_key
            state.reversal_signal = None
            state.reversal_count = 0
            state.reversal_last_seen_at = None
            return state, {
                "quick_signal": state.active_signal,
                "state": "active",
                "stability_cycles": max(required_cycles, state.candidate_count),
                "active_age_seconds": active_age,
                "cooldown_seconds_remaining": 0,
                "state_reason": "Opposite direction appeared, but the current active signal is still inside its minimum hold window.",
            }

        reversal_signal = raw_signal if raw_signal in BUY_SIGNALS else "Wait"
        fresh_market_data = state.last_data_key != data_key
        if state.reversal_signal == reversal_signal and fresh_market_data:
            state.reversal_count += 1
        elif state.reversal_signal != reversal_signal:
            state.reversal_signal = reversal_signal
            state.reversal_count = 1
        state.reversal_last_seen_at = now_iso
        state.last_data_key = data_key or state.last_data_key
        state.confidence = confidence

        required_reversal_cycles = 1 if fast_track else 2
        if state.reversal_count < required_reversal_cycles:
            pending_reason = (
                "Opposite direction appeared; waiting for one more confirming cycle before exiting."
                if reversal_signal in BUY_SIGNALS
                else "Follow-through paused; waiting for one more cycle before closing the active trade."
            )
            return state, {
                "quick_signal": state.active_signal,
                "state": "active",
                "stability_cycles": max(required_cycles, state.candidate_count),
                "active_age_seconds": active_age,
                "cooldown_seconds_remaining": 0,
                "state_reason": pending_reason,
            }

        state.state = "cooldown"
        state.candidate_signal = raw_signal if raw_signal in BUY_SIGNALS else None
        state.candidate_count = 1 if raw_signal in BUY_SIGNALS else 0
        state.active_signal = None
        state.reversal_signal = None
        state.reversal_count = 0
        state.reversal_last_seen_at = None
        state.cooldown_until = (now_utc + timedelta(seconds=profile.cooldown_seconds)).isoformat()
        return state, {
            "quick_signal": "Wait",
            "state": "cooldown",
            "stability_cycles": 0,
            "active_age_seconds": active_age,
            "cooldown_seconds_remaining": profile.cooldown_seconds,
            "state_reason": "Active signal ended after reversal/weakening persisted across two cycles.",
        }

    if raw_signal in BUY_SIGNALS:
        fresh_market_data = state.last_data_key != data_key
        if state.candidate_signal == raw_signal and state.last_data_key != data_key:
            state.candidate_count += 1
        elif state.candidate_signal != raw_signal:
            state.candidate_signal = raw_signal
            state.candidate_count = 1

        state.state = "candidate"
        state.confidence = confidence
        state.last_seen_at = now_iso
        state.last_data_key = data_key
        state.reversal_signal = None
        state.reversal_count = 0
        state.reversal_last_seen_at = None

        if not fresh_market_data and state.candidate_count < required_cycles:
            return state, {
                "quick_signal": "Wait",
                "state": "candidate",
                "stability_cycles": state.candidate_count,
                "active_age_seconds": 0,
                "cooldown_seconds_remaining": 0,
                "state_reason": "Setup is unchanged; waiting for the next fresh market update before activation.",
            }

        if state.candidate_count >= required_cycles:
            state.state = "active"
            state.active_signal = raw_signal
            state.activated_at = now_iso
            state.cooldown_until = None
            return state, {
                "quick_signal": raw_signal,
                "state": "active",
                "stability_cycles": state.candidate_count,
                "active_age_seconds": 0,
                "cooldown_seconds_remaining": 0,
                "state_reason": "Directional quick signal confirmed and activated.",
            }

        return state, {
            "quick_signal": "Wait",
            "state": "candidate",
            "stability_cycles": state.candidate_count,
            "active_age_seconds": 0,
            "cooldown_seconds_remaining": 0,
            "state_reason": "Setup forming; waiting for another confirming cycle before activation.",
        }

    state.state = "idle"
    state.candidate_signal = None
    state.candidate_count = 0
    state.active_signal = None
    state.activated_at = None
    state.last_seen_at = now_iso
    state.cooldown_until = None
    state.confidence = confidence
    state.last_data_key = data_key
    state.reversal_signal = None
    state.reversal_count = 0
    state.reversal_last_seen_at = None
    return state, {
        "quick_signal": "Wait",
        "state": "idle",
        "stability_cycles": 0,
        "active_age_seconds": 0,
        "cooldown_seconds_remaining": 0,
        "state_reason": "No quick setup currently meets activation standards.",
    }
