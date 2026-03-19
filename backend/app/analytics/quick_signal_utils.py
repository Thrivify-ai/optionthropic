"""
Pure helpers for quick signal filtering.
"""

from __future__ import annotations


def has_directional_persistence(momentum_1m: float, momentum_prev_leg: float | None, direction: str) -> bool:
    if momentum_prev_leg is None:
        return True
    if direction == "bullish":
        return momentum_1m > 0 and momentum_prev_leg > 0
    if direction == "bearish":
        return momentum_1m < 0 and momentum_prev_leg < 0
    return False


def is_quick_rangebound(
    spot: float,
    support: float | None,
    resistance: float | None,
    momentum_1m: float,
    momentum_3m: float | None,
    bull_threshold: float,
    mom_3m_threshold: float,
) -> bool:
    if support is None or resistance is None:
        return False
    inside_range = support <= spot <= resistance
    weak_1m = abs(momentum_1m) < max(1.0, bull_threshold * 0.5)
    weak_3m = momentum_3m is None or abs(momentum_3m) < max(1.0, mom_3m_threshold * 0.75)
    return inside_range and weak_1m and weak_3m
