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
from datetime import datetime

from app.analytics.main_signal_runtime import LongSignalContext
from app.analytics.signal_engine import Bias, Signal, TradingSignal

_MOMENTUM_THRESHOLDS = {
    "5m": (0.0015, 0.0030),
    "30m": (0.0025, 0.0050),
    "60m": (0.0040, 0.0080),
}
_MAIN_MIN_CONFIDENCE = 78

_SUPPORTIVE_BULLISH_BUILDS = {"Long buildup", "Short covering"}
_SUPPORTIVE_BEARISH_BUILDS = {"Short buildup", "Long unwinding"}


@dataclass
class FeatureView:
    timeframe: str
    current_price: float
    prev_price: float
    snapshot_timestamp: datetime | None = None
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


def _price_above(level: float | None, price: float, *, buffer_pct: float = 0.0004) -> bool:
    if level is None:
        return False
    return float(price) >= float(level) * (1.0 + buffer_pct)


def _price_below(level: float | None, price: float, *, buffer_pct: float = 0.0004) -> bool:
    if level is None:
        return False
    return float(price) <= float(level) * (1.0 - buffer_pct)


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


def _breadth_supports_outlook(context: LongSignalContext | None, outlook: Bias, *, min_score: int = 14) -> bool:
    if context is None or not context.breadth_available:
        return True
    if outlook == Bias.BULLISH:
        return int(context.breadth_score or 0) >= min_score and context.breadth_direction == "bullish"
    if outlook == Bias.BEARISH:
        return int(context.breadth_score or 0) <= -min_score and context.breadth_direction == "bearish"
    return True


def _structure_bias_counts(
    current_features: tuple[FeatureView, FeatureView, FeatureView],
    context: LongSignalContext | None,
) -> tuple[int, int, list[str]]:
    if context is None:
        return 0, 0, []

    f5 = current_features[0]
    price = float(f5.current_price)
    bull = 0
    bear = 0
    reasons: list[str] = []

    if context.session_vwap is not None:
        if _price_above(context.session_vwap, price, buffer_pct=0.0002):
            bull += 1
        elif _price_below(context.session_vwap, price, buffer_pct=0.0002):
            bear += 1

    if context.opening_range_high is not None and context.opening_range_low is not None:
        if _price_above(context.opening_range_high, price, buffer_pct=0.0002):
            bull += 2
            reasons.append("Price is holding above the opening range.")
        elif _price_below(context.opening_range_low, price, buffer_pct=0.0002):
            bear += 2
            reasons.append("Price is holding below the opening range.")
        elif context.session_bucket in {"MIDDAY", "CLOSING"}:
            reasons.append("Price is still trapped inside the opening range.")

    if context.previous_day_high is not None and _price_above(context.previous_day_high, price, buffer_pct=0.0004):
        bull += 1
        reasons.append("Price is trading above the previous day high.")
    elif context.previous_day_low is not None and _price_below(context.previous_day_low, price, buffer_pct=0.0004):
        bear += 1
        reasons.append("Price is trading below the previous day low.")

    if context.previous_day_close is not None:
        if price > context.previous_day_close:
            bull += 1
        elif price < context.previous_day_close:
            bear += 1

    return bull, bear, list(dict.fromkeys(reasons))


def _effective_barrier(
    feature: FeatureView,
    direction: Bias,
    context: LongSignalContext | None,
) -> tuple[float | None, str | None]:
    price = float(feature.current_price)
    if direction == Bias.BULLISH:
        candidates: list[tuple[float, str]] = []
        if feature.resistance_strike is not None and feature.resistance_strike > price:
            candidates.append((float(feature.resistance_strike), "options resistance"))
        if context is not None:
            if context.opening_range_high is not None and context.opening_range_high > price:
                candidates.append((float(context.opening_range_high), "opening range high"))
            if context.previous_day_high is not None and context.previous_day_high > price:
                candidates.append((float(context.previous_day_high), "previous day high"))
        if not candidates:
            return None, None
        return min(candidates, key=lambda item: item[0])

    candidates = []
    if feature.support_strike is not None and feature.support_strike < price:
        candidates.append((float(feature.support_strike), "options support"))
    if context is not None:
        if context.opening_range_low is not None and context.opening_range_low < price:
            candidates.append((float(context.opening_range_low), "opening range low"))
        if context.previous_day_low is not None and context.previous_day_low < price:
            candidates.append((float(context.previous_day_low), "previous day low"))
    if not candidates:
        return None, None
    return max(candidates, key=lambda item: item[0])


def _reward_risk_penalty(
    feature: FeatureView,
    direction: Bias,
    context: LongSignalContext | None,
) -> tuple[int, str | None]:
    if feature.current_price <= 0:
        return 0, None

    barrier, barrier_name = _effective_barrier(feature, direction, context)
    if direction == Bias.BULLISH and barrier is not None:
        headroom = barrier - feature.current_price
        required = max(feature.current_price * 0.0025, 20.0)
        if headroom <= 0:
            return 12, f"Price is already pressing into {barrier_name or 'resistance'}."
        if headroom < required:
            return 8, f"Upside room is limited before {barrier_name or 'resistance'}."

    if direction == Bias.BEARISH and barrier is not None:
        headroom = feature.current_price - barrier
        required = max(feature.current_price * 0.0025, 20.0)
        if headroom <= 0:
            return 12, f"Price is already pressing into {barrier_name or 'support'}."
        if headroom < required:
            return 8, f"Downside room is limited before {barrier_name or 'support'}."

    return 0, None


def _determine_outlook(
    current_features: tuple[FeatureView, FeatureView, FeatureView],
    context: LongSignalContext | None,
) -> Bias:
    f5, f30, f60 = current_features
    b5 = _bias_from_feature(f5)
    b30 = _bias_from_feature(f30)
    b60 = _bias_from_feature(f60)
    structure_bull, structure_bear, _ = _structure_bias_counts(current_features, context)

    if any(feature.trap_warning_flag for feature in current_features):
        return Bias.NEUTRAL

    if f30.price_rangebound and f60.price_rangebound and f30.rangebound_oi_both_sides and f60.rangebound_oi_both_sides:
        return Bias.NEUTRAL

    if context is not None:
        if context.breadth_available:
            if b30 == Bias.BULLISH and b60 == Bias.BULLISH and not _breadth_supports_outlook(context, Bias.BULLISH):
                return Bias.NEUTRAL
            if b30 == Bias.BEARISH and b60 == Bias.BEARISH and not _breadth_supports_outlook(context, Bias.BEARISH):
                return Bias.NEUTRAL
        if (
            context.event_profile in {"event", "event_expiry"}
            and b30 != b60
            and abs(structure_bull - structure_bear) <= 1
        ):
            return Bias.NEUTRAL
        if context.is_expiry_day and context.session_bucket == "CLOSING":
            if structure_bull < 3 and structure_bear < 3:
                return Bias.NEUTRAL
        if (
            context.news_impact_score >= 85
            and context.session_bucket in {"OPENING", "MIDDAY"}
            and context.opening_range_high is not None
            and context.opening_range_low is not None
            and not _price_above(context.opening_range_high, float(f5.current_price), buffer_pct=0.0002)
            and not _price_below(context.opening_range_low, float(f5.current_price), buffer_pct=0.0002)
        ):
            return Bias.NEUTRAL
        if (
            context.session_bucket == "MIDDAY"
            and context.opening_range_high is not None
            and context.opening_range_low is not None
            and not _price_above(context.opening_range_high, float(f5.current_price), buffer_pct=0.0002)
            and not _price_below(context.opening_range_low, float(f5.current_price), buffer_pct=0.0002)
            and abs(structure_bull - structure_bear) <= 1
        ):
            return Bias.NEUTRAL

    if b30 == b60 and b30 != Bias.NEUTRAL:
        if b30 == Bias.BULLISH and structure_bull >= structure_bear:
            return Bias.BULLISH
        if b30 == Bias.BEARISH and structure_bear >= structure_bull:
            return Bias.BEARISH
        if abs(structure_bull - structure_bear) <= 1 and _momentum_strength(f60) >= 2:
            return b30

    if b60 != Bias.NEUTRAL and b5 == b60 and b30 == Bias.NEUTRAL and _momentum_strength(f60) >= 1:
        if b60 == Bias.BULLISH and structure_bull >= structure_bear + 1:
            return Bias.BULLISH
        if b60 == Bias.BEARISH and structure_bear >= structure_bull + 1:
            return Bias.BEARISH

    return Bias.NEUTRAL


def _entry_ready(
    features: tuple[FeatureView, FeatureView, FeatureView],
    outlook: Bias,
    context: LongSignalContext | None,
) -> bool:
    if outlook == Bias.NEUTRAL:
        return False

    f5, f30, f60 = features
    bias_5m = _bias_from_feature(f5)
    if bias_5m not in {outlook, Bias.NEUTRAL}:
        return False
    if f5.price_rangebound and f5.rangebound_oi_both_sides:
        return False
    if not _breadth_supports_outlook(context, outlook):
        return False

    price = float(f5.current_price)
    above_vwap = context is None or context.session_vwap is None or _price_above(context.session_vwap, price, buffer_pct=0.0)
    below_vwap = context is None or context.session_vwap is None or _price_below(context.session_vwap, price, buffer_pct=0.0)
    above_finish_levels = (
        context is None
        or (_price_above(context.opening_range_high, price, buffer_pct=0.0002) if context.opening_range_high is not None else False)
        or (_price_above(context.previous_day_high, price, buffer_pct=0.0004) if context.previous_day_high is not None else False)
    )
    below_finish_levels = (
        context is None
        or (_price_below(context.opening_range_low, price, buffer_pct=0.0002) if context.opening_range_low is not None else False)
        or (_price_below(context.previous_day_low, price, buffer_pct=0.0004) if context.previous_day_low is not None else False)
    )
    stricter_profile = context is not None and context.event_profile in {"event", "event_expiry", "expiry"}
    news_shock_guard = context is not None and context.news_impact_score >= 85
    low_volatility_guard = context is not None and context.intraday_volatility_ratio < 0.82

    if outlook == Bias.BULLISH:
        continuation_override_bull = (
            bias_5m == Bias.NEUTRAL
            and _momentum_strength(f30) >= 2
            and _momentum_strength(f60) >= 2
            and above_vwap
            and above_finish_levels
            and (f30.breakout_flag or f60.breakout_flag or _supportive_build(f30, outlook))
        )
        bullish_checks = 0
        if f5.breakout_flag:
            bullish_checks += 1
        if f5.volume_spike:
            bullish_checks += 1
        if above_finish_levels:
            bullish_checks += 1
        if _supportive_build(f5, outlook):
            bullish_checks += 1
        if _supportive_build(f30, outlook) and _momentum_strength(f5) >= 2:
            bullish_checks += 1
        if _momentum_strength(f30) >= 1 and _momentum_strength(f60) >= 1:
            bullish_checks += 1
        if context is not None and context.breadth_available and context.breadth_score >= 18:
            bullish_checks += 1
        normal_ready = bullish_checks >= 3 and _momentum_strength(f5) >= 1 and (
            f5.breakout_flag or (_momentum_strength(f5) >= 2 and f5.volume_spike)
        )
        if news_shock_guard and not (f5.breakout_flag and f5.volume_spike) and not continuation_override_bull:
            return False
        if low_volatility_guard and not f5.breakout_flag and not continuation_override_bull:
            return False
        if stricter_profile:
            return above_vwap and above_finish_levels and (
                (
                    bullish_checks >= 3
                    and (f5.breakout_flag or (_momentum_strength(f5) >= 2 and f5.volume_spike))
                )
                or continuation_override_bull
            )
        return above_vwap and (normal_ready or continuation_override_bull)

    continuation_override_bear = (
        bias_5m == Bias.NEUTRAL
        and _momentum_strength(f30) >= 2
        and _momentum_strength(f60) >= 2
        and below_vwap
        and below_finish_levels
        and (f30.breakdown_flag or f60.breakdown_flag or _supportive_build(f30, outlook))
    )
    bearish_checks = 0
    if f5.breakdown_flag:
        bearish_checks += 1
    if f5.volume_spike:
        bearish_checks += 1
    if below_finish_levels:
        bearish_checks += 1
    if _supportive_build(f5, outlook):
        bearish_checks += 1
    if _supportive_build(f30, outlook) and _momentum_strength(f5) >= 2:
        bearish_checks += 1
    if _momentum_strength(f30) >= 1 and _momentum_strength(f60) >= 1:
        bearish_checks += 1
    if context is not None and context.breadth_available and context.breadth_score <= -18:
        bearish_checks += 1
    normal_ready = bearish_checks >= 3 and _momentum_strength(f5) >= 1 and (
        f5.breakdown_flag or (_momentum_strength(f5) >= 2 and f5.volume_spike)
    )
    if news_shock_guard and not (f5.breakdown_flag and f5.volume_spike) and not continuation_override_bear:
        return False
    if low_volatility_guard and not f5.breakdown_flag and not continuation_override_bear:
        return False
    if stricter_profile:
        return below_vwap and below_finish_levels and (
            (
                bearish_checks >= 3
                and (f5.breakdown_flag or (_momentum_strength(f5) >= 2 and f5.volume_spike))
            )
            or continuation_override_bear
        )
    return below_vwap and (normal_ready or continuation_override_bear)


def _confidence_from_features(
    features: tuple[FeatureView, FeatureView, FeatureView],
    outlook: Bias,
    context: LongSignalContext | None,
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
        if _momentum_strength(f5) >= 1:
            score += 6
            reasons.append("5m momentum is strong enough to support execution.")
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
    if _momentum_strength(f5) == 0:
        score -= 6
        reasons.append("5m momentum is still soft for a high-conviction trade.")

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

    structure_bull, structure_bear, structure_reasons = _structure_bias_counts(features, context)
    if context is not None:
        price = float(f5.current_price)
        if context.session_vwap is not None:
            if outlook == Bias.BULLISH and _price_above(context.session_vwap, price, buffer_pct=0.0):
                score += 6
                reasons.append("Price is holding above session VWAP.")
            elif outlook == Bias.BEARISH and _price_below(context.session_vwap, price, buffer_pct=0.0):
                score += 6
                reasons.append("Price is holding below session VWAP.")
            else:
                score -= 8
                reasons.append("Price is trading on the wrong side of session VWAP.")

        if structure_reasons:
            if (
                outlook == Bias.BULLISH and structure_bull > structure_bear
            ) or (
                outlook == Bias.BEARISH and structure_bear > structure_bull
            ):
                score += 6
                reasons.extend(structure_reasons)
            elif structure_bull == structure_bear:
                score -= 4
                reasons.append("Market structure is still balanced around key intraday levels.")
            else:
                score -= 6
                reasons.append("Market structure is leaning against the higher-timeframe bias.")

        if context.breadth_available:
            if _breadth_supports_outlook(context, outlook):
                score += 8
                reasons.append("Internal breadth and leadership are aligned with the finish bias.")
            else:
                score -= 14
                reasons.append("Internal breadth is diverging from the higher-timeframe bias.")

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
        previous_outlook = _determine_outlook(previous_features, context)
        if previous_outlook == outlook:
            score += 8
            reasons.append("The higher-timeframe outlook has persisted across two cycles.")
            if entry_ready and _entry_ready(previous_features, outlook, context):
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

    rr_penalty, rr_reason = _reward_risk_penalty(f30, outlook, context)
    if rr_penalty:
        score -= rr_penalty
        if rr_reason:
            reasons.append(rr_reason)

    if context is not None:
        if context.intraday_volatility_ratio < 0.82 and not aligned_break:
            score -= 8
            reasons.append("Intraday volatility is compressed, so the setup needs more proof than it currently has.")
        elif context.intraday_volatility_ratio > 1.3 and aligned_break:
            score += 4
            reasons.append("Volatility expansion is supporting the directional move.")
        if context.event_profile in {"event", "event_expiry"}:
            score -= 10
            reasons.append("Global event risk is elevated, so the finish bias needs extra caution.")
        elif context.event_profile == "expiry":
            score -= 8
            reasons.append("Expiry proximity is increasing intraday noise.")
        elif context.expiry_bucket == "1DTE":
            score -= 3
            reasons.append("Near-expiry positioning adds some noise.")

    quality_penalty = 0
    for feature in (f60, f30, f5):
        if feature.data_quality_score < 80:
            quality_penalty += 5
    if quality_penalty:
        score -= quality_penalty
        reasons.append("Some feature snapshots have weaker data quality.")

    return max(0, min(100, score)), reasons


def determine_main_outlook(
    current_features: tuple[FeatureView, FeatureView, FeatureView],
    context: LongSignalContext | None = None,
) -> Bias:
    return _determine_outlook(current_features, context)


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
    context: LongSignalContext | None = None,
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

    outlook = _determine_outlook(current_features, context)
    if outlook == Bias.NEUTRAL:
        neutral_reason = "Higher-timeframe structure is mixed. The market has not shown a stable directional outlook yet."
        if context is not None and context.event_profile in {"event", "event_expiry"}:
            neutral_reason = "Event-day conditions are noisy and higher-timeframe structure is not stable enough yet."
        elif context is not None and context.is_expiry_day:
            neutral_reason = "Expiry-day structure is still pinning price around intraday levels. Waiting for a cleaner finish bias."
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=25 if any(bias != Bias.NEUTRAL for bias in current_biases) else 0,
            support=support,
            resistance=resistance,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason=neutral_reason,
        )

    entry_ready = _entry_ready(current_features, outlook, context)
    confidence, parts = _confidence_from_features(
        current_features,
        outlook,
        context,
        previous_features=previous_features,
        entry_ready=entry_ready,
    )
    reason = " ".join(dict.fromkeys(parts))

    if not entry_ready:
        if _bias_from_feature(f5) != outlook:
            suffix = f"{outlook.value} finish bias is intact, but 5m entry timing is not aligned yet."
        else:
            suffix = f"{outlook.value} finish bias is intact, but entry confirmation is still developing."
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
        previous_outlook = _determine_outlook(previous_features, context)
        previous_entry_ready = _entry_ready(previous_features, outlook, context) if previous_outlook == outlook else False
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

    if confidence < _MAIN_MIN_CONFIDENCE:
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=confidence,
            support=support,
            resistance=resistance,
            bias_5m=current_biases[0],
            bias_30m=current_biases[1],
            bias_60m=current_biases[2],
            reason=f"{reason} Outlook is {outlook.value.lower()}, but confidence {confidence}% is still below the {_MAIN_MIN_CONFIDENCE}% activation threshold.".strip(),
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
