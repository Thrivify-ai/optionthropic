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
    confirm_cycles: int
    min_hold_seconds: int
    cooldown_seconds: int


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


def session_profile_for(now_utc: datetime | None = None) -> QuickSignalSessionProfile:
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    now_ist = current.astimezone(timezone(timedelta(hours=5, minutes=30)))

    if now_ist.weekday() > 4:
        return QuickSignalSessionProfile("closed", 1.35, 90, 99, 0, 0)

    t = now_ist.time()
    if dtime(9, 0) <= t < dtime(10, 15):
        return QuickSignalSessionProfile("opening", 1.10, 76, 2, 120, 90)
    if dtime(10, 15) <= t < dtime(13, 30):
        return QuickSignalSessionProfile("midday", 1.25, 82, 3, 150, 120)
    if dtime(13, 30) <= t <= dtime(15, 30):
        return QuickSignalSessionProfile("closing", 1.12, 78, 2, 120, 90)
    return QuickSignalSessionProfile("closed", 1.35, 90, 99, 0, 0)


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
    required_headroom = max(target_move * 0.4, spot * 0.0015)
    if signal == "Buy CE":
        if breakout:
            return True, "Breakout cleared near resistance"
        if resistance is None:
            return True, "No nearby resistance wall"
        headroom = resistance - spot
        if headroom >= required_headroom:
            return True, f"Upside headroom {headroom:.0f} pts"
        return False, f"Upside headroom only {headroom:.0f} pts before resistance"

    if signal == "Buy PE":
        if breakdown:
            return True, "Breakdown cleared near support"
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
    trap: bool,
    rangebound: bool,
    risk_reward_ok: bool,
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
        score += 12
    if risk_reward_ok:
        score += 10

    if trap:
        score -= 35
    if rangebound:
        score -= 25
    if not risk_reward_ok:
        score -= 20

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
    )

    activated_at = _parse_ts(state.activated_at)
    cooldown_until = _parse_ts(state.cooldown_until)
    active_age = int((now_utc - activated_at).total_seconds()) if activated_at else 0
    cooldown_remaining = int((cooldown_until - now_utc).total_seconds()) if cooldown_until and cooldown_until > now_utc else 0

    if hard_invalidation and state.active_signal:
        state.state = "cooldown"
        state.candidate_signal = None
        state.candidate_count = 0
        state.active_signal = None
        state.cooldown_until = (now_utc + timedelta(seconds=profile.cooldown_seconds)).isoformat()
        state.confidence = confidence
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
        state.confidence = confidence
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
            return state, {
                "quick_signal": state.active_signal,
                "state": "active",
                "stability_cycles": max(profile.confirm_cycles, state.candidate_count),
                "active_age_seconds": active_age,
                "cooldown_seconds_remaining": 0,
                "state_reason": "Active signal remains aligned and confirmed.",
            }

        if raw_signal == "Wait" and active_age < profile.min_hold_seconds:
            state.state = "active"
            state.confidence = max(state.confidence, confidence)
            return state, {
                "quick_signal": state.active_signal,
                "state": "active",
                "stability_cycles": max(profile.confirm_cycles, state.candidate_count),
                "active_age_seconds": active_age,
                "cooldown_seconds_remaining": 0,
                "state_reason": "Holding the active signal through a brief pause inside the minimum hold window.",
            }

        if raw_signal in BUY_SIGNALS and raw_signal != state.active_signal and active_age < profile.min_hold_seconds:
            state.state = "active"
            return state, {
                "quick_signal": state.active_signal,
                "state": "active",
                "stability_cycles": max(profile.confirm_cycles, state.candidate_count),
                "active_age_seconds": active_age,
                "cooldown_seconds_remaining": 0,
                "state_reason": "Opposite direction appeared, but the current active signal is still inside its minimum hold window.",
            }

        state.state = "cooldown"
        state.candidate_signal = raw_signal if raw_signal in BUY_SIGNALS else None
        state.candidate_count = 1 if raw_signal in BUY_SIGNALS else 0
        state.active_signal = None
        state.cooldown_until = (now_utc + timedelta(seconds=profile.cooldown_seconds)).isoformat()
        state.confidence = confidence
        return state, {
            "quick_signal": "Wait",
            "state": "cooldown",
            "stability_cycles": 0,
            "active_age_seconds": active_age,
            "cooldown_seconds_remaining": profile.cooldown_seconds,
            "state_reason": "Active signal ended and has moved into cooldown.",
        }

    if raw_signal in BUY_SIGNALS:
        if state.candidate_signal == raw_signal:
            state.candidate_count += 1
        else:
            state.candidate_signal = raw_signal
            state.candidate_count = 1

        state.state = "candidate"
        state.confidence = confidence
        state.last_seen_at = now_iso

        if state.candidate_count >= profile.confirm_cycles:
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
    return state, {
        "quick_signal": "Wait",
        "state": "idle",
        "stability_cycles": 0,
        "active_age_seconds": 0,
        "cooldown_seconds_remaining": 0,
        "state_reason": "No quick setup currently meets activation standards.",
    }
