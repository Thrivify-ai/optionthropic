"""
Signal engine for multi-timeframe options-based trade signals.

Design goals:
- Very few, high-quality signals.
- Default is WAIT.
- Only emit BUY CE / BUY PE when all three timeframes (5m, 30m, 60m)
  agree on direction AND confidence_score >= 70.

This module is written to be used from a background job that runs
every 60 seconds. The background job should:
- Load / aggregate data for 5m, 30m, 60m windows from the DB
- Build SnapshotInput objects
- Call generate_trading_signal(...)
- Persist the resulting signal into a trading_signals table

The API layer should then read the latest signal from that table and
return it quickly, without heavy computation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional, Dict, Any


class Bias(str, Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"


class Signal(str, Enum):
    BUY_CE = "Buy CE"
    BUY_PE = "Buy PE"
    WAIT = "Wait"


Timeframe = Literal["5m", "30m", "60m"]


@dataclass
class SnapshotInput:
    """
    Aggregated inputs for ONE timeframe window (5m / 30m / 60m).

    This is intentionally \"pre-aggregated\". The background collector
    should compute these from raw per-strike data and persist them.
    """

    timeframe: Timeframe
    symbol: str

    current_price: float
    prev_price: float

    total_put_oi: float
    total_call_oi: float
    total_put_oi_prev: float
    total_call_oi_prev: float

    support_strike: Optional[float]
    resistance_strike: Optional[float]
    support_holding: bool
    resistance_holding: bool

    near_support_put_oi_change: float
    near_resistance_call_oi_change: float

    price_broke_support: bool
    price_broke_resistance: bool
    call_oi_drop_after_break: bool
    put_oi_drop_after_break: bool

    rangebound_oi_both_sides: bool
    price_rangebound: bool


@dataclass
class SnapshotBias:
    timeframe: Timeframe
    bias: Bias
    pcr: Optional[float]
    pcr_sentiment: Bias
    position_buildup: Optional[str]
    writer_bullish: bool
    writer_bearish: bool
    liquidity_trap: Optional[str]
    rangebound: bool
    details: Dict[str, Any]


@dataclass
class TradingSignal:
    symbol: str
    signal: Signal
    confidence: int
    support: Optional[float]
    resistance: Optional[float]
    bias_5m: Bias
    bias_30m: Bias
    bias_60m: Bias
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "signal": self.signal.value,
            "confidence": self.confidence,
            "support": self.support,
            "resistance": self.resistance,
            "bias_5m": self.bias_5m.value,
            "bias_30m": self.bias_30m.value,
            "bias_60m": self.bias_60m.value,
            "reason": self.reason,
        }


def _compute_pcr(total_put_oi: float, total_call_oi: float) -> Optional[float]:
    if total_call_oi <= 0:
        return None
    return total_put_oi / total_call_oi


def _interpret_pcr(pcr: Optional[float]) -> Bias:
    if pcr is None:
        return Bias.NEUTRAL
    if pcr > 1.1:
        return Bias.BULLISH
    if pcr < 0.9:
        return Bias.BEARISH
    return Bias.NEUTRAL


def _detect_position_buildup(
    current_price: float,
    prev_price: float,
    total_put_oi: float,
    total_call_oi: float,
    total_put_oi_prev: float,
    total_call_oi_prev: float,
) -> Optional[str]:
    """
    Returns:
      \"Long buildup\", \"Short buildup\", \"Short covering\",
      \"Long unwinding\", or None.
    """
    price_change = current_price - prev_price
    oi_change = (total_put_oi + total_call_oi) - (total_put_oi_prev + total_call_oi_prev)
    if current_price <= 0 or prev_price <= 0:
        return None

    price_up = price_change > 0
    price_down = price_change < 0
    oi_up = oi_change > 0
    oi_down = oi_change < 0

    if price_up and oi_up:
        return "Long buildup"
    if price_down and oi_up:
        return "Short buildup"
    if price_up and oi_down:
        return "Short covering"
    if price_down and oi_down:
        return "Long unwinding"
    return None


def _detect_writer_dominance(snapshot: SnapshotInput) -> tuple[bool, bool]:
    """
    Returns:
      (writer_bullish, writer_bearish)
    based on OI changes near support/resistance.
    """
    bull_writer = False
    bear_writer = False

    if snapshot.near_support_put_oi_change > 0 and snapshot.near_resistance_call_oi_change < 0:
        bull_writer = True

    if snapshot.near_resistance_call_oi_change > 0 and snapshot.near_support_put_oi_change < 0:
        bear_writer = True

    return bull_writer, bear_writer


def detect_liquidity_trap(snapshot: SnapshotInput) -> Optional[str]:
    """
    Step 5 — Liquidity trap detection.
    """
    price_up = snapshot.current_price > snapshot.prev_price
    price_down = snapshot.current_price < snapshot.prev_price

    if snapshot.price_broke_resistance and snapshot.call_oi_drop_after_break and price_down:
        return "Bull trap"

    if snapshot.price_broke_support and snapshot.put_oi_drop_after_break and price_up:
        return "Bear trap"

    return None


def calculate_snapshot_bias(snapshot: SnapshotInput) -> SnapshotBias:
    """
    Calculate Bullish / Bearish / Neutral bias for a single timeframe.

    Uses a multi-factor scoring system so the bias is never locked behind
    a single condition that may be unavailable (e.g. writer-dominance data).

    Scoring (each factor is independent):
      +2 / -2  PCR sentiment (most reliable standalone signal)
      +1 / -1  Price direction with level holding
      +1 / -1  Writer dominance (only when OI-delta data is non-zero)
      +1 / -1  Position buildup pattern
      ─────────────────────────────────────────
      >= +2  → BULLISH
      <= -2  → BEARISH
      otherwise NEUTRAL
    Liquidity traps always force NEUTRAL regardless of score.
    """
    pcr            = _compute_pcr(snapshot.total_put_oi, snapshot.total_call_oi)
    pcr_sentiment  = _interpret_pcr(pcr)
    position_buildup = _detect_position_buildup(
        snapshot.current_price,
        snapshot.prev_price,
        snapshot.total_put_oi,
        snapshot.total_call_oi,
        snapshot.total_put_oi_prev,
        snapshot.total_call_oi_prev,
    )
    writer_bullish, writer_bearish = _detect_writer_dominance(snapshot)
    trap       = detect_liquidity_trap(snapshot)
    price_up   = snapshot.current_price > snapshot.prev_price
    price_down = snapshot.current_price < snapshot.prev_price
    rangebound = snapshot.price_rangebound and snapshot.rangebound_oi_both_sides

    if trap is not None:
        bias = Bias.NEUTRAL
    else:
        bull = 0
        bear = 0

        # ── Factor 1: PCR (strongest signal, worth 2 pts) ─────────────────
        if pcr_sentiment == Bias.BULLISH:
            bull += 2
        elif pcr_sentiment == Bias.BEARISH:
            bear += 2

        # ── Factor 2: Price direction + support/resistance holding ─────────
        if price_up and snapshot.support_holding:
            bull += 1
        elif price_down and snapshot.resistance_holding:
            bear += 1

        # ── Factor 3: Writer dominance (only when delta data is present) ───
        s_change = snapshot.near_support_put_oi_change
        r_change = snapshot.near_resistance_call_oi_change
        if s_change != 0.0 or r_change != 0.0:
            if s_change > r_change:
                bull += 1   # put writers defending support → bullish
            elif r_change > s_change:
                bear += 1   # call writers capping resistance → bearish

        # ── Factor 4: Position buildup ─────────────────────────────────────
        if position_buildup in ("Long buildup", "Short covering"):
            bull += 1
        elif position_buildup in ("Short buildup", "Long unwinding"):
            bear += 1

        # ── Resolve ────────────────────────────────────────────────────────
        if bull >= 2 and bull > bear:
            bias = Bias.BULLISH
        elif bear >= 2 and bear > bull:
            bias = Bias.BEARISH
        else:
            bias = Bias.NEUTRAL

    return SnapshotBias(
        timeframe=snapshot.timeframe,
        bias=bias,
        pcr=pcr,
        pcr_sentiment=pcr_sentiment,
        position_buildup=position_buildup,
        writer_bullish=writer_bullish,
        writer_bearish=writer_bearish,
        liquidity_trap=trap,
        rangebound=rangebound,
        details={
            "support":      snapshot.support_strike,
            "resistance":   snapshot.resistance_strike,
            "price_up":     price_up,
            "price_down":   price_down,
            "put_oi_change":  snapshot.total_put_oi  - snapshot.total_put_oi_prev,
            "call_oi_change": snapshot.total_call_oi - snapshot.total_call_oi_prev,
        },
    )


def detect_rangebound_market(
    bias_5m: SnapshotBias,
    bias_30m: SnapshotBias,
    bias_60m: SnapshotBias,
) -> bool:
    """
    Rangebound if all three frames are rangebound or long-term is rangebound
    and shorter frames are neutral.
    """
    if bias_5m.rangebound and bias_30m.rangebound and bias_60m.rangebound:
        return True

    if bias_60m.rangebound and bias_5m.bias == Bias.NEUTRAL and bias_30m.bias == Bias.NEUTRAL:
        return True

    return False


def calculate_confidence_score(
    bias_5m: SnapshotBias,
    bias_30m: SnapshotBias,
    bias_60m: SnapshotBias,
    final_bias: Optional[Bias],
) -> int:
    """
    Confidence between 0 and 100 based on:
      - Timeframe alignment (strongest factor)
      - PCR strength
      - Writer activity
      - Position buildup
    """
    if final_bias is None or final_bias == Bias.NEUTRAL:
        return 0

    score = 0
    max_score = 0

    max_score += 40
    if (
        bias_5m.bias == final_bias
        and bias_30m.bias == final_bias
        and bias_60m.bias == final_bias
    ):
        score += 40
    elif (
        bias_5m.bias == final_bias
        and bias_30m.bias == final_bias
        or bias_30m.bias == final_bias
        and bias_60m.bias == final_bias
    ):
        score += 25
    else:
        score += 10

    for b in (bias_5m, bias_30m, bias_60m):
        max_score += 10
        if b.pcr is None:
            continue
        if b.pcr_sentiment == final_bias:
            if b.pcr > 1.3 or b.pcr < 0.7:
                score += 10
            else:
                score += 6
        elif b.pcr_sentiment == Bias.NEUTRAL:
            score += 3

    for b in (bias_5m, bias_30m, bias_60m):
        max_score += 10
        if final_bias == Bias.BULLISH and b.writer_bullish:
            score += 8
        elif final_bias == Bias.BEARISH and b.writer_bearish:
            score += 8
        else:
            score += 2

    for b in (bias_5m, bias_30m, bias_60m):
        max_score += 10
        if b.position_buildup is None:
            continue
        if final_bias == Bias.BULLISH and b.position_buildup in ("Long buildup", "Short covering"):
            score += 8
        elif final_bias == Bias.BEARISH and b.position_buildup in ("Short buildup", "Long unwinding"):
            score += 8
        else:
            score += 2

    if max_score == 0:
        return 0

    raw = int(round(score / max_score * 100))
    return max(0, min(100, raw))


def generate_trading_signal(
    symbol: str,
    snap_5m: SnapshotInput,
    snap_30m: SnapshotInput,
    snap_60m: SnapshotInput,
) -> TradingSignal:
    """
    High-level orchestration:
    - Compute snapshot biases
    - Check for liquidity traps (force WAIT)
    - Check multi-timeframe agreement
    - Detect rangebound market (force WAIT)
    - Compute confidence score
    - Only emit BUY CE / BUY PE if confidence >= 70, else WAIT
    """
    b5 = calculate_snapshot_bias(snap_5m)
    b30 = calculate_snapshot_bias(snap_30m)
    b60 = calculate_snapshot_bias(snap_60m)

    if any(b.liquidity_trap for b in (b5, b30, b60)):
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=0,
            support=snap_60m.support_strike,
            resistance=snap_60m.resistance_strike,
            bias_5m=b5.bias,
            bias_30m=b30.bias,
            bias_60m=b60.bias,
            reason="Liquidity trap detected in at least one timeframe – standing aside.",
        )

    bullish_all = b5.bias == Bias.BULLISH and b30.bias == Bias.BULLISH and b60.bias == Bias.BULLISH
    bearish_all = b5.bias == Bias.BEARISH and b30.bias == Bias.BEARISH and b60.bias == Bias.BEARISH

    final_bias: Optional[Bias] = None
    final_signal: Signal = Signal.WAIT

    if bullish_all:
        final_bias = Bias.BULLISH
        final_signal = Signal.BUY_CE
    elif bearish_all:
        final_bias = Bias.BEARISH
        final_signal = Signal.BUY_PE

    if detect_rangebound_market(b5, b30, b60):
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=0,
            support=snap_60m.support_strike,
            resistance=snap_60m.resistance_strike,
            bias_5m=b5.bias,
            bias_30m=b30.bias,
            bias_60m=b60.bias,
            reason="Rangebound market detected – price stuck between support and resistance with OI on both sides.",
        )

    if final_bias is None:
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=0,
            support=snap_60m.support_strike,
            resistance=snap_60m.resistance_strike,
            bias_5m=b5.bias,
            bias_30m=b30.bias,
            bias_60m=b60.bias,
            reason="Timeframes disagree – no strong directional consensus.",
        )

    confidence = calculate_confidence_score(b5, b30, b60, final_bias)

    if confidence < 70:
        return TradingSignal(
            symbol=symbol,
            signal=Signal.WAIT,
            confidence=confidence,
            support=snap_60m.support_strike,
            resistance=snap_60m.resistance_strike,
            bias_5m=b5.bias,
            bias_30m=b30.bias,
            bias_60m=b60.bias,
            reason=f"Directional bias is {final_bias.value} but confidence {confidence}% is below 70% threshold.",
        )

    reason = []
    reason.append(f"{final_bias.value} momentum across 5m, 30m, and 60m snapshots.")
    if any(b.writer_bullish for b in (b5, b30, b60)) and final_bias == Bias.BULLISH:
        reason.append("Put writers defending support and calls being unwound.")
    if any(b.writer_bearish for b in (b5, b30, b60)) and final_bias == Bias.BEARISH:
        reason.append("Call writers defending resistance and puts being unwound.")
    if any(b.position_buildup for b in (b5, b30, b60)):
        reason.append("Consistent OI/price buildup pattern supporting the move.")

    return TradingSignal(
        symbol=symbol,
        signal=final_signal,
        confidence=confidence,
        support=snap_60m.support_strike,
        resistance=snap_60m.resistance_strike,
        bias_5m=b5.bias,
        bias_30m=b30.bias,
        bias_60m=b60.bias,
        reason=" ".join(reason),
    )

