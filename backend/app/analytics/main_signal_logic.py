"""
Pure main signal decision logic built on feature snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analytics.signal_engine import Bias, Signal, TradingSignal


@dataclass
class FeatureView:
    timeframe: str
    current_price: float
    prev_price: float
    pcr_oi: float | None
    support_strike: float | None
    resistance_strike: float | None
    near_support_put_oi_change: int
    near_resistance_call_oi_change: int
    writer_bullish_score: int
    writer_bearish_score: int
    position_buildup: str | None
    volume_spike: bool
    price_rangebound: bool
    rangebound_oi_both_sides: bool
    breakout_flag: bool
    breakdown_flag: bool
    trap_warning_flag: bool


def _bias_from_feature(feature: FeatureView) -> Bias:
    bull = 0
    bear = 0

    if feature.pcr_oi is not None:
        if feature.pcr_oi > 1.1:
            bull += 2
        elif feature.pcr_oi < 0.9:
            bear += 2

    if feature.current_price > feature.prev_price:
        bull += 1
    elif feature.current_price < feature.prev_price:
        bear += 1

    bull += feature.writer_bullish_score
    bear += feature.writer_bearish_score

    if feature.position_buildup in ("Long buildup", "Short covering"):
        bull += 1
    elif feature.position_buildup in ("Short buildup", "Long unwinding"):
        bear += 1

    if feature.breakout_flag:
        bull += 1
    if feature.breakdown_flag:
        bear += 1

    if feature.trap_warning_flag:
        return Bias.NEUTRAL
    if feature.price_rangebound and feature.rangebound_oi_both_sides:
        return Bias.NEUTRAL
    if bull >= 3 and bull > bear:
        return Bias.BULLISH
    if bear >= 3 and bear > bull:
        return Bias.BEARISH
    return Bias.NEUTRAL


def _confidence_from_features(features: tuple[FeatureView, FeatureView, FeatureView], final_bias: Bias) -> int:
    score = 0

    if all(_bias_from_feature(feature) == final_bias for feature in features):
        score += 45

    for feature in features:
        if feature.volume_spike:
            score += 5
        if final_bias == Bias.BULLISH and feature.writer_bullish_score:
            score += 5
        if final_bias == Bias.BEARISH and feature.writer_bearish_score:
            score += 5
        if final_bias == Bias.BULLISH and feature.position_buildup in ("Long buildup", "Short covering"):
            score += 5
        if final_bias == Bias.BEARISH and feature.position_buildup in ("Short buildup", "Long unwinding"):
            score += 5
        if feature.trap_warning_flag:
            score -= 15
        if feature.price_rangebound:
            score -= 10

    return max(0, min(100, score))


def generate_main_signal_from_features(
    symbol: str,
    current_features: tuple[FeatureView, FeatureView, FeatureView],
    previous_features: tuple[FeatureView, FeatureView, FeatureView] | None,
) -> TradingSignal:
    f5, f30, f60 = current_features
    current_biases = tuple(_bias_from_feature(feature) for feature in current_features)

    if any(feature.trap_warning_flag for feature in current_features):
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=0,
            support=f60.support_strike,
            resistance=f60.resistance_strike,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason="Trap risk detected in feature snapshots. Standing aside.",
        )

    if all(feature.price_rangebound and feature.rangebound_oi_both_sides for feature in current_features):
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=0,
            support=f60.support_strike,
            resistance=f60.resistance_strike,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason="All tracked timeframes are rangebound with OI on both sides.",
        )

    if current_biases == (Bias.BULLISH, Bias.BULLISH, Bias.BULLISH):
        final_bias = Bias.BULLISH
        final_signal = Signal.BUY_CE
    elif current_biases == (Bias.BEARISH, Bias.BEARISH, Bias.BEARISH):
        final_bias = Bias.BEARISH
        final_signal = Signal.BUY_PE
    else:
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=0,
            support=f60.support_strike,
            resistance=f60.resistance_strike,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason="Feature timeframes are not directionally aligned.",
        )

    if previous_features is not None:
        previous_biases = tuple(_bias_from_feature(feature) for feature in previous_features)
        if previous_biases != current_biases:
            return TradingSignal(
                symbol=symbol,
                signal=Signal.WAIT,
                confidence=0,
                support=f60.support_strike,
                resistance=f60.resistance_strike,
                bias_5m=current_biases[0],
                bias_30m=current_biases[1],
                bias_60m=current_biases[2],
                reason="Directional setup is forming but has not persisted for two feature cycles yet.",
            )

    confidence = _confidence_from_features(current_features, final_bias)
    if confidence < 70:
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=confidence,
            support=f60.support_strike,
            resistance=f60.resistance_strike,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason=f"Aligned setup detected, but confidence {confidence}% is below threshold.",
        )

    return TradingSignal(
        symbol=symbol,
        signal=final_signal,
        confidence=confidence,
        support=f60.support_strike,
        resistance=f60.resistance_strike,
        bias_5m=current_biases[0],
        bias_30m=current_biases[1],
        bias_60m=current_biases[2],
        reason=f"{final_bias.value} alignment confirmed across 5m, 30m, and 60m feature snapshots.",
    )
