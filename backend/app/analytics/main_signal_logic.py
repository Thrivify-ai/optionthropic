"""
Pure main signal decision logic built on feature snapshots.

Quick signals and long signals now have distinct jobs:
- quick signals: capture fast intraday movement
- main signals: express the higher-timeframe market outlook and only promote
  to Buy CE / Buy PE when entry timing is also ready

The main engine is intentionally conservative. It should tell us where the
market is leaning, but still prefer WAIT over a forced entry.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analytics.signal_engine import Bias, Signal, TradingSignal

_MOMENTUM_THRESHOLDS = {
    "5m": (0.0015, 0.0030),
    "30m": (0.0025, 0.0050),
    "60m": (0.0040, 0.0080),
}

_SUPPORTIVE_BULLISH_BUILDS = {"Long buildup", "Short covering"}
_SUPPORTIVE_BEARISH_BUILDS = {"Short buildup", "Long unwinding"}


@dataclass
class FeatureView:
    timeframe: str
    current_price: float
    prev_price: float
    price_change_pct: float = 0.0
    pcr_oi: float | None = None
    support_strike: float | None = None
    resistance_strike: float | None = None
    near_support_put_oi_change: int = 0
    near_resistance_call_oi_change: int = 0
    writer_bullish_score: int = 0
    writer_bearish_score: int = 0
    position_buildup: str | None = None
    volume_spike: bool = False
    price_rangebound: bool = False
    rangebound_oi_both_sides: bool = False
    breakout_flag: bool = False
    breakdown_flag: bool = False
    trap_warning_flag: bool = False
    data_quality_score: int = 100


def _momentum_strength(feature: FeatureView) -> int:
    weak, strong = _MOMENTUM_THRESHOLDS.get(feature.timeframe, (0.0025, 0.0050))
    move = abs(feature.price_change_pct)
    if move >= strong:
        return 2
    if move >= weak:
        return 1
    return 0


def _price_bias(feature: FeatureView) -> Bias:
    if feature.current_price > feature.prev_price:
        return Bias.BULLISH
    if feature.current_price < feature.prev_price:
        return Bias.BEARISH
    return Bias.NEUTRAL


def _bias_from_feature(feature: FeatureView) -> Bias:
    bull = 0
    bear = 0

    if feature.trap_warning_flag:
        return Bias.NEUTRAL
    if feature.price_rangebound and feature.rangebound_oi_both_sides:
        return Bias.NEUTRAL

    if feature.pcr_oi is not None:
        if feature.pcr_oi > 1.1:
            bull += 2
        elif feature.pcr_oi < 0.9:
            bear += 2

    price_bias = _price_bias(feature)
    if price_bias == Bias.BULLISH:
        bull += 1
    elif price_bias == Bias.BEARISH:
        bear += 1

    bull += feature.writer_bullish_score
    bear += feature.writer_bearish_score

    if feature.position_buildup in _SUPPORTIVE_BULLISH_BUILDS:
        bull += 1
    elif feature.position_buildup in _SUPPORTIVE_BEARISH_BUILDS:
        bear += 1

    if feature.breakout_flag:
        bull += 1
    if feature.breakdown_flag:
        bear += 1

    if bull >= 3 and bull > bear:
        return Bias.BULLISH
    if bear >= 3 and bear > bull:
        return Bias.BEARISH
    return Bias.NEUTRAL


def _supportive_build(feature: FeatureView, direction: Bias) -> bool:
    if direction == Bias.BULLISH:
        return feature.position_buildup in _SUPPORTIVE_BULLISH_BUILDS
    if direction == Bias.BEARISH:
        return feature.position_buildup in _SUPPORTIVE_BEARISH_BUILDS
    return False


def _reward_risk_penalty(feature: FeatureView, direction: Bias) -> tuple[int, str | None]:
    if feature.current_price <= 0:
        return 0, None

    if direction == Bias.BULLISH and feature.resistance_strike is not None:
        headroom = feature.resistance_strike - feature.current_price
        required = max(feature.current_price * 0.0025, 20.0)
        if headroom <= 0:
            return 12, "Price is already pressing into resistance."
        if headroom < required:
            return 8, "Upside room is limited before resistance."

    if direction == Bias.BEARISH and feature.support_strike is not None:
        headroom = feature.current_price - feature.support_strike
        required = max(feature.current_price * 0.0025, 20.0)
        if headroom <= 0:
            return 12, "Price is already pressing into support."
        if headroom < required:
            return 8, "Downside room is limited before support."

    return 0, None


def _determine_outlook(current_features: tuple[FeatureView, FeatureView, FeatureView]) -> Bias:
    f5, f30, f60 = current_features
    b5 = _bias_from_feature(f5)
    b30 = _bias_from_feature(f30)
    b60 = _bias_from_feature(f60)

    if any(feature.trap_warning_flag for feature in current_features):
        return Bias.NEUTRAL

    if f30.price_rangebound and f60.price_rangebound and f30.rangebound_oi_both_sides and f60.rangebound_oi_both_sides:
        return Bias.NEUTRAL

    if b30 == b60 and b30 != Bias.NEUTRAL:
        return b30

    if b60 != Bias.NEUTRAL and b5 == b60 and b30 == Bias.NEUTRAL and _momentum_strength(f60) >= 1:
        return b60

    return Bias.NEUTRAL


def _entry_ready(features: tuple[FeatureView, FeatureView, FeatureView], outlook: Bias) -> bool:
    if outlook == Bias.NEUTRAL:
        return False

    f5, f30, _ = features
    bias_5m = _bias_from_feature(f5)
    if bias_5m != outlook:
        return False
    if f5.price_rangebound and f5.rangebound_oi_both_sides:
        return False

    if outlook == Bias.BULLISH:
        return (
            f5.breakout_flag
            or f5.volume_spike
            or (_supportive_build(f5, outlook) and _momentum_strength(f5) >= 1)
            or (_supportive_build(f30, outlook) and _momentum_strength(f5) >= 2)
        )

    return (
        f5.breakdown_flag
        or f5.volume_spike
        or (_supportive_build(f5, outlook) and _momentum_strength(f5) >= 1)
        or (_supportive_build(f30, outlook) and _momentum_strength(f5) >= 2)
    )


def _confidence_from_features(
    features: tuple[FeatureView, FeatureView, FeatureView],
    outlook: Bias,
    *,
    previous_features: tuple[FeatureView, FeatureView, FeatureView] | None,
    entry_ready: bool,
) -> tuple[int, list[str]]:
    f5, f30, f60 = features
    reasons: list[str] = []

    if outlook == Bias.NEUTRAL:
        return 0, reasons

    score = 0

    score += 30
    reasons.append(f"60m regime and 30m structure are both {outlook.value.lower()}.")

    if entry_ready:
        score += 12
        reasons.append("5m timing is aligned for entry.")
    else:
        bias_5m = _bias_from_feature(f5)
        if bias_5m == outlook:
            score += 6
            reasons.append("5m timing is leaning the right way but is not fully ready.")
        elif bias_5m == Bias.NEUTRAL:
            reasons.append("5m timing is still neutral.")
        else:
            score -= 10
            reasons.append("5m timing is still opposing the higher-timeframe outlook.")

    for feature in (f60, f30, f5):
        score += _momentum_strength(feature) * 4

    if _momentum_strength(f60) >= 1:
        reasons.append("Higher-timeframe momentum is present.")
    if _momentum_strength(f30) >= 1:
        reasons.append("30m structure has directional follow-through.")

    aligned_break = (
        outlook == Bias.BULLISH and (f30.breakout_flag or f5.breakout_flag)
    ) or (
        outlook == Bias.BEARISH and (f30.breakdown_flag or f5.breakdown_flag)
    )
    if aligned_break:
        score += 8
        reasons.append("Breakout structure supports the direction.")

    writer_support = 0
    build_support = 0
    pcr_support = 0
    for feature in (f60, f30, f5):
        if outlook == Bias.BULLISH and feature.writer_bullish_score:
            writer_support += 1
        if outlook == Bias.BEARISH and feature.writer_bearish_score:
            writer_support += 1
        if _supportive_build(feature, outlook):
            build_support += 1
        if feature.pcr_oi is not None:
            if outlook == Bias.BULLISH and feature.pcr_oi > 1.05:
                pcr_support += 1
            elif outlook == Bias.BEARISH and feature.pcr_oi < 0.95:
                pcr_support += 1

    if writer_support:
        score += writer_support * 4
        reasons.append("Writer dominance supports the outlook.")
    if build_support:
        score += build_support * 4
        reasons.append("Position buildup supports the outlook.")
    if pcr_support:
        score += pcr_support * 3
        reasons.append("PCR remains supportive.")

    if f5.volume_spike and entry_ready:
        score += 4
        reasons.append("Short-term participation improved.")

    if previous_features is not None:
        previous_outlook = _determine_outlook(previous_features)
        if previous_outlook == outlook:
            score += 8
            reasons.append("The higher-timeframe outlook has persisted across two cycles.")
            if entry_ready and _entry_ready(previous_features, outlook):
                score += 6
                reasons.append("Entry timing has also persisted across two cycles.")
        else:
            score -= 8
            reasons.append("The outlook is still fresh and has not fully stabilized yet.")

    range_penalty = 0
    if f30.price_rangebound and f30.rangebound_oi_both_sides:
        range_penalty += 12
    if f60.price_rangebound and f60.rangebound_oi_both_sides:
        range_penalty += 15
    if range_penalty:
        score -= range_penalty
        reasons.append("Rangebound conditions are reducing confidence.")

    rr_penalty, rr_reason = _reward_risk_penalty(f30, outlook)
    if rr_penalty:
        score -= rr_penalty
        if rr_reason:
            reasons.append(rr_reason)

    quality_penalty = 0
    for feature in (f60, f30, f5):
        if feature.data_quality_score < 80:
            quality_penalty += 5
    if quality_penalty:
        score -= quality_penalty
        reasons.append("Some feature snapshots have weaker data quality.")

    return max(0, min(100, score)), reasons


def derive_signal_context(
    signal: str,
    bias_5m: str,
    bias_30m: str,
    bias_60m: str,
    confidence: int,
) -> dict[str, object]:
    if signal in ("Buy CE", "Buy PE", "Hold CE", "Hold PE"):
        outlook = "Bullish" if signal == "Buy CE" else "Bearish"
        if signal == "Hold CE":
            outlook = "Bullish"
        if signal == "Hold PE":
            outlook = "Bearish"
        return {"outlook": outlook, "state": "active", "entry_ready": True}

    if signal in ("Exit CE", "Exit PE"):
        outlook = "Bullish" if signal == "Exit CE" else "Bearish"
        return {"outlook": outlook, "state": "exit", "entry_ready": False}

    if bias_60m == bias_30m and bias_60m in ("Bullish", "Bearish"):
        state = "setup" if confidence >= 45 else "watch"
        return {"outlook": bias_60m, "state": state, "entry_ready": False}

    if bias_60m in ("Bullish", "Bearish"):
        return {"outlook": bias_60m, "state": "watch", "entry_ready": False}

    return {"outlook": "Neutral", "state": "idle", "entry_ready": False}


def generate_main_signal_from_features(
    symbol: str,
    current_features: tuple[FeatureView, FeatureView, FeatureView],
    previous_features: tuple[FeatureView, FeatureView, FeatureView] | None,
) -> TradingSignal:
    f5, f30, f60 = current_features
    current_biases = tuple(_bias_from_feature(feature) for feature in current_features)
    support = f30.support_strike if f30.support_strike is not None else f60.support_strike
    resistance = (
        f30.resistance_strike if f30.resistance_strike is not None else f60.resistance_strike
    )

    if any(feature.trap_warning_flag for feature in current_features):
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=0,
            support=support,
            resistance=resistance,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason="Trap risk is visible in the current feature set. Standing aside until structure resets.",
        )

    if (
        f30.price_rangebound
        and f60.price_rangebound
        and f30.rangebound_oi_both_sides
        and f60.rangebound_oi_both_sides
    ):
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=0,
            support=support,
            resistance=resistance,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason="30m and 60m are both rangebound with OI on both sides. No higher-timeframe edge yet.",
        )

    outlook = _determine_outlook(current_features)
    if outlook == Bias.NEUTRAL:
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=25 if any(bias != Bias.NEUTRAL for bias in current_biases) else 0,
            support=support,
            resistance=resistance,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason="Higher-timeframe structure is mixed. The market has not shown a stable directional outlook yet.",
        )

    entry_ready = _entry_ready(current_features, outlook)
    confidence, parts = _confidence_from_features(
        current_features,
        outlook,
        previous_features=previous_features,
        entry_ready=entry_ready,
    )
    reason = " ".join(dict.fromkeys(parts))

    if not entry_ready:
        if _bias_from_feature(f5) != outlook:
            suffix = f"{outlook.value} outlook is intact, but 5m timing is not aligned yet."
        else:
            suffix = f"{outlook.value} outlook is intact, but entry confirmation is still developing."
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=confidence,
            support=support,
            resistance=resistance,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason=f"{reason} {suffix}".strip(),
        )

    if previous_features is not None:
        previous_outlook = _determine_outlook(previous_features)
        previous_entry_ready = _entry_ready(previous_features, outlook) if previous_outlook == outlook else False
        if previous_outlook != outlook or not previous_entry_ready:
            return TradingSignal(
                symbol=symbol,
                signal=Signal.WAIT,
                confidence=confidence,
                support=support,
                resistance=resistance,
                bias_5m=current_biases[0],
                bias_30m=current_biases[1],
                bias_60m=current_biases[2],
                reason=f"{reason} The outlook is present, but the entry has not persisted for two cycles yet.".strip(),
            )

    if confidence < 70:
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=confidence,
            support=support,
            resistance=resistance,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason=f"{reason} Outlook is {outlook.value.lower()}, but confidence {confidence}% is still below the activation threshold.".strip(),
        )

    final_signal = Signal.BUY_CE if outlook == Bias.BULLISH else Signal.BUY_PE
    return TradingSignal(
        symbol=symbol,
        signal=final_signal,
        confidence=confidence,
        support=support,
        resistance=resistance,
        bias_5m=current_biases[0],
        bias_30m=current_biases[1],
        bias_60m=current_biases[2],
        reason=f"{reason} {outlook.value} outlook and entry timing are both confirmed.".strip(),
    )
