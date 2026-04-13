"""
Weekend sandbox market simulator.

This module generates deterministic intraday-style price paths with swings,
trend days, trap days, and news shocks. The synthetic stream is then pushed
through the same quick-signal confidence/lifecycle logic and the same long
signal engine used in production so we can validate signal quality without
polluting live data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import random
from statistics import mean
from typing import Any

from app.analytics.main_signal_logic import FeatureView, derive_signal_context, generate_main_signal_from_features
from app.analytics.main_signal_runtime import LongSignalContext
from app.analytics.quick_signal_phase2 import (
    BUY_SIGNALS,
    QuickSignalLifecycleState,
    apply_lifecycle,
    quick_signal_confidence,
    reward_risk_ok,
    session_profile_for,
)
from app.analytics.signal_engine import Bias


@dataclass(frozen=True)
class SandboxSymbolProfile:
    symbol: str
    base_price: float
    quick_target: float
    quick_1m: float
    quick_3m: float
    quick_5m: float
    long_success: float
    long_stop: float
    quick_success: float
    quick_stop: float
    support_gap: float


@dataclass
class SandboxTradeState:
    signal: str
    direction: int
    entry_price: float
    success_threshold: float
    stop_threshold: float
    hold_steps: int = 0
    max_favorable: float = 0.0
    max_adverse: float = 0.0


@dataclass(frozen=True)
class SandboxScenario:
    name: str
    description: str
    phases: tuple[tuple[str, float], ...]


_SCENARIOS: dict[str, SandboxScenario] = {
    "trend_up_news": SandboxScenario(
        name="trend_up_news",
        description="Compression, bullish news break, trend follow-through, then a healthy pullback.",
        phases=(
            ("compression", 0.18),
            ("breakout_up", 0.12),
            ("trend_up", 0.34),
            ("pullback_hold", 0.16),
            ("grind_up", 0.20),
        ),
    ),
    "trend_down_news": SandboxScenario(
        name="trend_down_news",
        description="Compression, bearish news break, slide, brief pause, then continuation lower.",
        phases=(
            ("compression", 0.16),
            ("breakdown", 0.12),
            ("trend_down", 0.34),
            ("pullback_short", 0.16),
            ("grind_down", 0.22),
        ),
    ),
    "range_whipsaw": SandboxScenario(
        name="range_whipsaw",
        description="Low-conviction oscillation with repeated false starts inside a range.",
        phases=(
            ("range_up", 0.22),
            ("range_down", 0.20),
            ("range_up", 0.20),
            ("range_down", 0.20),
            ("range_flat", 0.18),
        ),
    ),
    "bull_trap": SandboxScenario(
        name="bull_trap",
        description="Bullish breakout attempt that quickly fails and reverses lower.",
        phases=(
            ("compression", 0.20),
            ("breakout_up", 0.10),
            ("bull_trap_reversal", 0.20),
            ("trend_down", 0.30),
            ("range_flat", 0.20),
        ),
    ),
    "bear_trap": SandboxScenario(
        name="bear_trap",
        description="Bearish breakdown attempt that fails and snaps back higher.",
        phases=(
            ("compression", 0.20),
            ("breakdown", 0.10),
            ("bear_trap_reversal", 0.20),
            ("trend_up", 0.30),
            ("range_flat", 0.20),
        ),
    ),
}

_PROFILES: dict[str, SandboxSymbolProfile] = {
    "NIFTY": SandboxSymbolProfile("NIFTY", 23000.0, 35.0, 18.0, 12.0, 28.0, 20.0, 14.0, 10.0, 8.0, 70.0),
    "BANKNIFTY": SandboxSymbolProfile("BANKNIFTY", 52500.0, 80.0, 45.0, 30.0, 65.0, 45.0, 30.0, 25.0, 18.0, 160.0),
    "SENSEX": SandboxSymbolProfile("SENSEX", 74250.0, 100.0, 30.0, 22.0, 75.0, 60.0, 40.0, 30.0, 22.0, 180.0),
    "CRUDEOIL": SandboxSymbolProfile("CRUDEOIL", 6100.0, 28.0, 10.0, 20.0, 28.0, 45.0, 28.0, 20.0, 12.0, 56.0),
    "NATGAS": SandboxSymbolProfile("NATGAS", 285.0, 7.0, 2.0, 5.0, 7.0, 12.0, 8.0, 5.0, 3.0, 14.0),
    "GOLD": SandboxSymbolProfile("GOLD", 94800.0, 95.0, 35.0, 70.0, 95.0, 140.0, 90.0, 70.0, 45.0, 190.0),
    "SILVER": SandboxSymbolProfile("SILVER", 96000.0, 110.0, 40.0, 80.0, 110.0, 170.0, 110.0, 80.0, 55.0, 220.0),
}


def list_sandbox_scenarios() -> list[dict[str, str]]:
    return [
        {"name": scenario.name, "description": scenario.description}
        for scenario in _SCENARIOS.values()
    ]


def _phase_sequence(scenario: SandboxScenario, steps: int) -> list[str]:
    phases: list[str] = []
    remaining = steps
    for index, (name, ratio) in enumerate(scenario.phases):
        if index == len(scenario.phases) - 1:
            count = remaining
        else:
            count = max(1, int(round(steps * ratio)))
            remaining -= count
        phases.extend([name] * count)
    return phases[:steps]


def _phase_delta(profile: SandboxSymbolProfile, phase: str, rng: random.Random, step: int) -> float:
    target = profile.quick_target
    if phase == "compression":
        return rng.uniform(-0.15, 0.15) * target
    if phase == "breakout_up":
        return rng.uniform(0.65, 1.05) * target
    if phase == "breakdown":
        return -rng.uniform(0.65, 1.05) * target
    if phase == "trend_up":
        return rng.uniform(0.35, 0.75) * target
    if phase == "trend_down":
        return -rng.uniform(0.35, 0.75) * target
    if phase == "grind_up":
        return rng.uniform(0.10, 0.35) * target
    if phase == "grind_down":
        return -rng.uniform(0.10, 0.35) * target
    if phase == "pullback_hold":
        return rng.uniform(-0.30, 0.12) * target
    if phase == "pullback_short":
        return rng.uniform(-0.12, 0.30) * target
    if phase == "bull_trap_reversal":
        return -rng.uniform(0.75, 1.10) * target
    if phase == "bear_trap_reversal":
        return rng.uniform(0.75, 1.10) * target
    if phase == "range_up":
        sign = 1 if step % 2 == 0 else -1
        return sign * rng.uniform(0.08, 0.25) * target
    if phase == "range_down":
        sign = -1 if step % 2 == 0 else 1
        return sign * rng.uniform(0.08, 0.25) * target
    if phase == "range_flat":
        return rng.uniform(-0.08, 0.08) * target
    return rng.uniform(-0.10, 0.10) * target


def _recent_direction(prices: list[float], window: int = 6) -> tuple[int, float]:
    recent = prices[-window:]
    if len(recent) < 4:
        return 0, 0.0
    ups = downs = 0
    for index in range(1, len(recent)):
        if recent[index] > recent[index - 1]:
            ups += 1
        elif recent[index] < recent[index - 1]:
            downs += 1
    total = ups + downs
    if total == 0:
        return 0, 0.0
    return (1 if ups > downs else -1 if downs > ups else 0), max(ups, downs) / total


def _signal_to_direction(signal: str) -> int:
    if signal in {"Buy CE", "LONG"}:
        return 1
    if signal in {"Buy PE", "SHORT"}:
        return -1
    return 0


def _points(direction: int, entry_price: float, current_price: float) -> float:
    return round((current_price - entry_price) * direction, 2)


def _update_trade(
    trade: SandboxTradeState | None,
    *,
    signal: str,
    confidence: int,
    current_price: float,
    success_threshold: float,
    stop_threshold: float,
    exit_floor: int = 70,
) -> tuple[SandboxTradeState | None, dict[str, Any]]:
    if trade is None:
        direction = _signal_to_direction(signal)
        if direction == 0:
            return None, {"state": "idle", "public_signal": "WAIT", "points": None, "result": None}
        new_trade = SandboxTradeState(
            signal=signal,
            direction=direction,
            entry_price=current_price,
            success_threshold=success_threshold,
            stop_threshold=stop_threshold,
        )
        return new_trade, {"state": "entry", "public_signal": signal, "points": 0.0, "result": None}

    points = _points(trade.direction, trade.entry_price, current_price)
    trade.max_favorable = max(trade.max_favorable, points)
    trade.max_adverse = min(trade.max_adverse, points)
    trade.hold_steps += 1
    new_direction = _signal_to_direction(signal)

    if points <= -trade.stop_threshold:
        result = "stop"
        return None, {"state": "exit", "public_signal": "EXIT", "points": points, "result": result}
    if new_direction != 0 and new_direction != trade.direction and confidence >= exit_floor:
        result = "reversal_exit"
        return None, {"state": "exit", "public_signal": "EXIT", "points": points, "result": result}
    if points >= trade.success_threshold and new_direction == 0:
        result = "target_book"
        return None, {"state": "exit", "public_signal": "EXIT", "points": points, "result": result}

    return trade, {"state": "hold", "public_signal": "HOLD", "points": points, "result": None}


def _quick_eval(
    profile: SandboxSymbolProfile,
    symbol: str,
    *,
    now_utc: datetime,
    phase: str,
    prices: list[float],
    lifecycle: QuickSignalLifecycleState,
) -> tuple[QuickSignalLifecycleState, dict[str, Any]]:
    current = prices[-1]
    prev_1m = prices[-2] if len(prices) > 1 else current
    prev_3m = prices[-4] if len(prices) > 3 else prev_1m
    prev_5m = prices[-6] if len(prices) > 5 else prev_3m
    mom1 = round(current - prev_1m, 2)
    mom3 = round(current - prev_3m, 2)
    mom5 = round(current - prev_5m, 2)

    recent = prices[-12:]
    prior_prices = recent[:-1] if len(recent) > 1 else recent
    support = min(prior_prices) if prior_prices else current - profile.support_gap
    resistance = max(prior_prices) if prior_prices else current + profile.support_gap
    direction, consistency = _recent_direction(prices)

    breakout = current > resistance + profile.quick_target * 0.08
    breakdown = current < support - profile.quick_target * 0.08
    rangebound = phase.startswith("range") or phase == "compression"
    trap = phase in {"bull_trap_reversal", "bear_trap_reversal"}
    volume_spike = phase in {"breakout_up", "breakdown", "trend_up", "trend_down", "bull_trap_reversal", "bear_trap_reversal"}
    oi_confirmed_bull = phase in {"breakout_up", "trend_up", "grind_up", "pullback_hold"} and not trap
    oi_confirmed_bear = phase in {"breakdown", "trend_down", "grind_down", "pullback_short"} and not trap

    bullish = mom1 >= profile.quick_1m and mom3 >= profile.quick_3m
    bearish = mom1 <= -profile.quick_1m and mom3 <= -profile.quick_3m
    strong_3m_bull = mom3 >= profile.quick_3m and mom5 >= profile.quick_5m * 0.85
    strong_3m_bear = mom3 <= -profile.quick_3m and mom5 <= -profile.quick_5m * 0.85

    profile_window = session_profile_for(now_utc)
    confirmation_count_bull = sum((breakout, volume_spike, oi_confirmed_bull, strong_3m_bull, direction == 1 and consistency >= 0.65))
    confirmation_count_bear = sum((breakdown, volume_spike, oi_confirmed_bear, strong_3m_bear, direction == -1 and consistency >= 0.65))

    rr_ok_bull, rr_reason_bull = reward_risk_ok(
        "Buy CE",
        spot=current,
        support=support,
        resistance=resistance,
        target_move=profile.quick_target,
        breakout=breakout,
        breakdown=False,
    )
    rr_ok_bear, rr_reason_bear = reward_risk_ok(
        "Buy PE",
        spot=current,
        support=support,
        resistance=resistance,
        target_move=profile.quick_target,
        breakout=False,
        breakdown=breakdown,
    )

    bullish_confidence = quick_signal_confidence(
        bullish=bullish,
        bearish=False,
        strong_1m=mom1 >= profile.quick_1m,
        strong_3m=strong_3m_bull,
        breakout=breakout,
        breakdown=False,
        volume_spike=volume_spike,
        oi_confirmed=oi_confirmed_bull,
        persistent=direction == 1 and consistency >= 0.65,
        confirmation_count=confirmation_count_bull,
        fresh_data=True,
        trap=trap,
        rangebound=rangebound,
        risk_reward_ok=rr_ok_bull,
        breadth_aligned=direction >= 0,
        breadth_score=24 if direction > 0 else 0,
        short_covering_risk=0,
        volatility_ratio=1.0,
        session_name=profile_window.name,
    )
    bearish_confidence = quick_signal_confidence(
        bullish=False,
        bearish=bearish,
        strong_1m=mom1 <= -profile.quick_1m,
        strong_3m=strong_3m_bear,
        breakout=False,
        breakdown=breakdown,
        volume_spike=volume_spike,
        oi_confirmed=oi_confirmed_bear,
        persistent=direction == -1 and consistency >= 0.65,
        confirmation_count=confirmation_count_bear,
        fresh_data=True,
        trap=trap,
        rangebound=rangebound,
        risk_reward_ok=rr_ok_bear,
        breadth_aligned=direction <= 0,
        breadth_score=-24 if direction < 0 else 0,
        short_covering_risk=0,
        volatility_ratio=1.0,
        session_name=profile_window.name,
    )

    raw_signal = "Wait"
    confidence = max(bullish_confidence, bearish_confidence)
    required = profile_window.min_confirmation_count
    if bullish and confirmation_count_bull >= required and rr_ok_bull and not trap and not rangebound:
        raw_signal = "Buy CE"
        confidence = bullish_confidence
        reason = rr_reason_bull
        confirmations = confirmation_count_bull
    elif bearish and confirmation_count_bear >= required and rr_ok_bear and not trap and not rangebound:
        raw_signal = "Buy PE"
        confidence = bearish_confidence
        reason = rr_reason_bear
        confirmations = confirmation_count_bear
    else:
        reason = "Setup still developing"
        confirmations = max(confirmation_count_bull, confirmation_count_bear)

    fast_track = confidence >= profile_window.min_confidence + 8 and confirmations >= 2 and phase in {"breakout_up", "breakdown", "trend_up", "trend_down"}
    lifecycle_state, lifecycle_payload = apply_lifecycle(
        lifecycle,
        raw_signal=raw_signal,
        confidence=confidence,
        now_utc=now_utc,
        profile=profile_window,
        hard_invalidation=trap,
        data_key=f"{symbol}:{now_utc.isoformat()}",
        fast_track=fast_track,
    )
    lifecycle_payload.update(
        {
            "raw_signal": raw_signal,
            "confidence": confidence,
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "momentum_1m": mom1,
            "momentum_3m": mom3,
            "momentum_5m": mom5,
            "confirmation_count": confirmations,
            "required_confirmations": required,
            "reason": reason,
        }
    )
    return lifecycle_state, lifecycle_payload


def _phase_bias(phase: str) -> Bias:
    if phase in {"breakout_up", "trend_up", "grind_up", "pullback_hold", "bear_trap_reversal"}:
        return Bias.BULLISH
    if phase in {"breakdown", "trend_down", "grind_down", "pullback_short", "bull_trap_reversal"}:
        return Bias.BEARISH
    return Bias.NEUTRAL


def _position_buildup_for_bias(bias: Bias) -> str | None:
    if bias == Bias.BULLISH:
        return "Long buildup"
    if bias == Bias.BEARISH:
        return "Short buildup"
    return None


def _feature_view(
    *,
    timeframe: str,
    current: float,
    previous: float,
    support: float,
    resistance: float,
    phase: str,
    context_bias: Bias,
) -> FeatureView:
    price_change_pct = ((current - previous) / previous) if previous else 0.0
    bullish = context_bias == Bias.BULLISH
    bearish = context_bias == Bias.BEARISH
    price_rangebound = phase.startswith("range") or phase == "compression"
    trap_warning = phase in {"bull_trap_reversal", "bear_trap_reversal"}

    return FeatureView(
        timeframe=timeframe,
        current_price=current,
        prev_price=previous,
        price_change_pct=price_change_pct,
        pcr_oi=1.16 if bullish else 0.84 if bearish else 1.0,
        support_strike=round(support, 2),
        resistance_strike=round(resistance, 2),
        near_support_put_oi_change=120 if bullish else -40 if bearish else 30,
        near_resistance_call_oi_change=120 if bearish else -40 if bullish else 30,
        writer_bullish_score=1 if bullish else 0,
        writer_bearish_score=1 if bearish else 0,
        position_buildup=_position_buildup_for_bias(context_bias),
        volume_spike=phase in {"breakout_up", "breakdown", "trend_up", "trend_down"},
        price_rangebound=price_rangebound,
        rangebound_oi_both_sides=price_rangebound,
        breakout_flag=phase in {"breakout_up", "trend_up", "grind_up", "bear_trap_reversal"} and current > resistance,
        breakdown_flag=phase in {"breakdown", "trend_down", "grind_down", "bull_trap_reversal"} and current < support,
        trap_warning_flag=trap_warning,
        data_quality_score=100,
    )


def _long_context(profile: SandboxSymbolProfile, prices: list[float], now_utc: datetime, phase: str) -> LongSignalContext:
    opening_prices = prices[: min(15, len(prices))]
    opening_high = max(opening_prices) if opening_prices else None
    opening_low = min(opening_prices) if opening_prices else None
    price_avg = mean(prices) if prices else profile.base_price
    session_bucket = "OPENING"
    if len(prices) >= 45:
        session_bucket = "MIDDAY"
    if len(prices) >= 90:
        session_bucket = "CLOSING"
    news_score = 90 if "news" in phase or phase in {"breakout_up", "breakdown"} else 0
    event_profile = "event" if news_score >= 85 else "normal"
    return LongSignalContext(
        session_vwap=round(price_avg, 2),
        opening_range_high=round(opening_high, 2) if opening_high is not None else None,
        opening_range_low=round(opening_low, 2) if opening_low is not None else None,
        previous_day_high=round(profile.base_price + profile.support_gap * 0.9, 2),
        previous_day_low=round(profile.base_price - profile.support_gap * 0.9, 2),
        previous_day_close=round(profile.base_price, 2),
        session_bucket=session_bucket,
        news_impact_score=news_score,
        event_profile=event_profile,
        days_to_expiry=3,
        expiry_bucket="2_5DTE",
        is_expiry_day=False,
    )


def _make_long_signal(
    symbol: str,
    profile: SandboxSymbolProfile,
    *,
    prices: list[float],
    phase: str,
    previous_features: tuple[FeatureView, FeatureView, FeatureView] | None,
    now_utc: datetime,
) -> tuple[dict[str, Any], tuple[FeatureView, FeatureView, FeatureView] | None]:
    if len(prices) < 61:
        payload = {
            "signal": "Wait",
            "confidence": 0,
            "state": "idle",
            "entry_ready": False,
            "reason": "Not enough simulated history to evaluate 60-minute structure yet.",
            "outlook": "Neutral",
        }
        return payload, previous_features

    current = prices[-1]
    support = min(prices[-12:-1]) if len(prices) > 12 else current - profile.support_gap
    resistance = max(prices[-12:-1]) if len(prices) > 12 else current + profile.support_gap
    bias_5m = _phase_bias(phase)
    bias_30m = Bias.BULLISH if prices[-1] > prices[-31] else Bias.BEARISH if prices[-1] < prices[-31] else Bias.NEUTRAL
    bias_60m = Bias.BULLISH if prices[-1] > prices[-61] else Bias.BEARISH if prices[-1] < prices[-61] else Bias.NEUTRAL

    current_features = (
        _feature_view(timeframe="5m", current=current, previous=prices[-6], support=support, resistance=resistance, phase=phase, context_bias=bias_5m),
        _feature_view(timeframe="30m", current=current, previous=prices[-31], support=support, resistance=resistance, phase=phase, context_bias=bias_30m),
        _feature_view(timeframe="60m", current=current, previous=prices[-61], support=support, resistance=resistance, phase=phase, context_bias=bias_60m),
    )
    context = _long_context(profile, prices, now_utc, phase)
    result = generate_main_signal_from_features(symbol, current_features, previous_features, context=context)
    context_payload = derive_signal_context(
        result.signal.value,
        result.bias_5m.value,
        result.bias_30m.value,
        result.bias_60m.value,
        result.confidence,
    )
    payload = {
        "signal": result.signal.value,
        "confidence": result.confidence,
        "state": context_payload.get("state"),
        "entry_ready": bool(context_payload.get("entry_ready", result.signal.value != "Wait")),
        "reason": result.reason,
        "outlook": context_payload.get("outlook", "Neutral"),
        "support": result.support,
        "resistance": result.resistance,
    }
    return payload, current_features


def run_market_sandbox(
    *,
    symbol: str,
    scenario_name: str,
    steps: int = 120,
    seed: int = 7,
) -> dict[str, Any]:
    symbol_key = symbol.upper()
    if symbol_key not in _PROFILES:
        raise ValueError(f"Unsupported sandbox symbol: {symbol}")
    if scenario_name not in _SCENARIOS:
        raise ValueError(f"Unsupported sandbox scenario: {scenario_name}")
    if steps < 30:
        raise ValueError("Sandbox needs at least 30 steps to produce useful validation.")

    profile = _PROFILES[symbol_key]
    scenario = _SCENARIOS[scenario_name]
    rng = random.Random(seed)
    phases = _phase_sequence(scenario, steps)
    prices = [profile.base_price]
    start_utc = datetime(2026, 1, 5, 3, 45, tzinfo=timezone.utc)

    quick_lifecycle = QuickSignalLifecycleState()
    quick_trade: SandboxTradeState | None = None
    long_trade: SandboxTradeState | None = None
    previous_long_features: tuple[FeatureView, FeatureView, FeatureView] | None = None
    frames: list[dict[str, Any]] = []
    quick_results: list[float] = []
    long_results: list[float] = []

    for step in range(steps):
        phase = phases[step]
        price = max(1.0, round(prices[-1] + _phase_delta(profile, phase, rng, step), 2))
        prices.append(price)
        now_utc = start_utc + timedelta(minutes=step)

        quick_lifecycle, quick_payload = _quick_eval(
            profile,
            symbol_key,
            now_utc=now_utc,
            phase=phase,
            prices=prices,
            lifecycle=quick_lifecycle,
        )
        quick_trade, quick_trade_payload = _update_trade(
            quick_trade,
            signal=quick_payload.get("quick_signal", "Wait"),
            confidence=int(quick_payload.get("confidence") or 0),
            current_price=price,
            success_threshold=profile.quick_success,
            stop_threshold=profile.quick_stop,
        )
        if quick_trade_payload["state"] == "exit" and quick_trade_payload["points"] is not None:
            quick_results.append(float(quick_trade_payload["points"]))

        long_payload, previous_long_features = _make_long_signal(
            symbol_key,
            profile,
            prices=prices,
            phase=phase,
            previous_features=previous_long_features,
            now_utc=now_utc,
        )
        long_trade, long_trade_payload = _update_trade(
            long_trade,
            signal=long_payload.get("signal", "Wait"),
            confidence=int(long_payload.get("confidence") or 0),
            current_price=price,
            success_threshold=profile.long_success,
            stop_threshold=profile.long_stop,
            exit_floor=72,
        )
        if long_trade_payload["state"] == "exit" and long_trade_payload["points"] is not None:
            long_results.append(float(long_trade_payload["points"]))

        frames.append(
            {
                "step": step + 1,
                "timestamp": now_utc.isoformat(),
                "phase": phase,
                "price": price,
                "quick": {
                    "signal": quick_payload.get("quick_signal"),
                    "state": quick_trade_payload["state"],
                    "confidence": quick_payload.get("confidence"),
                    "confirmation_count": quick_payload.get("confirmation_count"),
                    "required_confirmations": quick_payload.get("required_confirmations"),
                    "points": quick_trade_payload["points"],
                    "reason": quick_payload.get("reason"),
                },
                "long": {
                    "signal": long_payload.get("signal"),
                    "state": long_trade_payload["state"],
                    "confidence": long_payload.get("confidence"),
                    "points": long_trade_payload["points"],
                    "outlook": long_payload.get("outlook"),
                    "reason": long_payload.get("reason"),
                },
            }
        )

    quick_wins = [points for points in quick_results if points >= profile.quick_success]
    long_wins = [points for points in long_results if points >= profile.long_success]
    return {
        "symbol": symbol_key,
        "scenario": scenario.name,
        "description": scenario.description,
        "steps": steps,
        "seed": seed,
        "frames": frames,
        "summary": {
            "quick": {
                "trades": len(quick_results),
                "wins": len(quick_wins),
                "losses": len([points for points in quick_results if points < 0]),
                "win_rate_pct": round(100 * len(quick_wins) / len(quick_results), 1) if quick_results else None,
                "avg_points": round(sum(quick_results) / len(quick_results), 2) if quick_results else None,
                "best_points": max(quick_results) if quick_results else None,
                "worst_points": min(quick_results) if quick_results else None,
            },
            "long": {
                "trades": len(long_results),
                "wins": len(long_wins),
                "losses": len([points for points in long_results if points < 0]),
                "win_rate_pct": round(100 * len(long_wins) / len(long_results), 1) if long_results else None,
                "avg_points": round(sum(long_results) / len(long_results), 2) if long_results else None,
                "best_points": max(long_results) if long_results else None,
                "worst_points": min(long_results) if long_results else None,
            },
        },
    }
