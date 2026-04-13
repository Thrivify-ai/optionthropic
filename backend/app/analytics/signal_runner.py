"""
Signal runner — computes and persists TradingSignal rows every collector cycle.

Alignment strategy: use the SAME data sources as the Market Sentiment panel
(PCR + gamma walls + max pain + options flow), mirror the frontend deriveAll()
scoring in Python, then require price-momentum confirmation from a 5-minute
snapshot before emitting a BUY signal.  This means Market Sentiment and Trade
Signals will always agree on direction; the only difference is that Trade
Signals also demands that price is actually MOVING in that direction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.main_signal_logic import (
    FeatureView,
    determine_main_outlook,
    derive_signal_context,
    generate_main_signal_from_features,
)
from app.analytics.main_signal_runtime import load_long_signal_context
from app.analytics.main_trade_management import derive_main_trade_management_plan
from app.analytics.gamma_detection import compute_gamma_walls
from app.analytics.max_pain_detection import compute_max_pain
from app.analytics.options_analysis import compute_pcr
from app.analytics.options_flow_detection import detect_options_flow
from app.analytics.quant_signal_capture import (
    build_quant_context,
    derive_shadow_signal,
    record_quant_signal_candidate,
    record_shadow_decision,
    refresh_pending_quant_signal_outcomes,
)
from app.analytics.signal_outcomes import (
    record_signal_outcome_candidate,
    refresh_pending_signal_outcomes,
)
from app.analytics.signal_engine import Bias, Signal, TradingSignal
from app.analytics.signal_text import fit_trading_signal_reason
from app.analytics.trade_manager import (
    apply_managed_trade_decision,
    get_open_trade_row,
    stop_threshold_points,
    success_threshold_points,
    trade_state_from_row,
)
from app.analytics.volatility_profile import scale_trade_thresholds
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.logging_config import get_logger
from app.models.chain_snapshot import ChainSnapshot
from app.models.signal_feature_snapshot import SignalFeatureSnapshot
from app.models.trading_signal import TradingSignalRow

logger = get_logger(__name__)


async def _latest_feature_views(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
    limit: int = 2,
) -> list[FeatureView]:
    rows = (
        await session.execute(
            select(SignalFeatureSnapshot)
            .where(
                SignalFeatureSnapshot.symbol == symbol,
                SignalFeatureSnapshot.timeframe == timeframe,
            )
            .order_by(SignalFeatureSnapshot.snapshot_timestamp.desc(), SignalFeatureSnapshot.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        FeatureView(
            timeframe=row.timeframe,
            current_price=float(row.current_price),
            prev_price=float(row.prev_price),
            snapshot_timestamp=row.snapshot_timestamp,
            price_change_pct=float(row.price_change_pct),
            pcr_oi=float(row.pcr_oi) if row.pcr_oi is not None else None,
            support_strike=float(row.support_strike) if row.support_strike is not None else None,
            resistance_strike=float(row.resistance_strike) if row.resistance_strike is not None else None,
            near_support_put_oi_change=int(row.near_support_put_oi_change),
            near_resistance_call_oi_change=int(row.near_resistance_call_oi_change),
            writer_bullish_score=int(row.writer_bullish_score),
            writer_bearish_score=int(row.writer_bearish_score),
            position_buildup=row.position_buildup,
            volume_spike=bool(row.volume_spike),
            price_rangebound=bool(row.price_rangebound),
            rangebound_oi_both_sides=bool(row.rangebound_oi_both_sides),
            breakout_flag=bool(row.breakout_flag),
            breakdown_flag=bool(row.breakdown_flag),
            trap_warning_flag=bool(row.trap_warning_flag),
            data_quality_score=int(row.data_quality_score),
        )
        for row in rows
    ]


# ─── Sentiment scoring (mirrors frontend deriveAll) ───────────────────────────

async def _compute_sentiment(session: AsyncSession, symbol: str) -> dict:
    """
    Compute the same 4-signal bias score as MarketBiasPanel.deriveAll().
    Returns a dict with: score, n_signals, bias, conf_label, pcr_oi,
    spot, call_wall, put_wall, max_pain, flow_summary.
    """
    try:
        pcr_data  = await compute_pcr(session, symbol)
    except Exception:
        pcr_data  = {}
    try:
        gamma_data = await compute_gamma_walls(session, symbol)
    except Exception:
        gamma_data = {}
    try:
        mp_data    = await compute_max_pain(session, symbol)
    except Exception:
        mp_data    = {}
    try:
        flow_data  = await detect_options_flow(session, symbol, top_n=20)
    except Exception:
        flow_data  = {}

    pcr_oi    = float(pcr_data.get("pcr_oi")             or 0)
    spot      = float(gamma_data.get("underlying_price")  or 0)
    call_wall = float(gamma_data.get("call_wall")          or 0)
    put_wall  = float(gamma_data.get("put_wall")           or 0)
    max_pain  = float(mp_data.get("max_pain_strike")       or 0)
    summary   = flow_data.get("summary") or {}
    flows     = flow_data.get("flows")   or []
    dom       = summary.get("dominant_flow") or ""
    call_prem = float(summary.get("total_call_premium") or 0)
    put_prem  = float(summary.get("total_put_premium")  or 0)

    score     = 0
    n_signals = 0

    # ── PCR (same thresholds as MarketBiasPanel: 1.2 / 1.0 / 0.8) ────────────
    if pcr_oi > 0:
        n_signals += 1
        if   pcr_oi > 1.2: score += 2
        elif pcr_oi > 1.0: score += 1
        elif pcr_oi < 0.8: score -= 2
        else:               score -= 1

    # ── Gamma wall position ────────────────────────────────────────────────────
    rng = call_wall - put_wall
    if spot and call_wall and put_wall and rng > 0:
        n_signals += 1
        pos = (spot - put_wall) / rng
        if   pos > 0.65: score += 1
        elif pos < 0.35: score -= 1

    # ── Max pain vs spot ──────────────────────────────────────────────────────
    if spot and max_pain:
        n_signals += 1
        if   max_pain > spot * 1.005: score += 1
        elif max_pain < spot * 0.995: score -= 1

    # ── Options flow dominance ────────────────────────────────────────────────
    if flows:
        n_signals += 1
        if   dom == "put_writing"  or put_prem  > call_prem * 1.5: score += 1
        elif dom == "call_writing" or call_prem > put_prem  * 1.5: score -= 1
        elif dom == "put_buying":                                    score -= 1
        elif dom == "call_buying":                                   score += 1

    # ── Bias label (same as MarketBiasPanel) ──────────────────────────────────
    if   score >= 2:  bias = Bias.BULLISH
    elif score <= -2: bias = Bias.BEARISH
    else:             bias = Bias.NEUTRAL

    # ── Confidence % ─────────────────────────────────────────────────────────
    max_s = n_signals * 2
    conf_pct = int(min(95, abs(score) / max_s * 100)) if max_s > 0 else 0

    conf_label = (
        "HIGH"   if conf_pct >= 65 else
        "MEDIUM" if conf_pct >= 40 else
        "LOW"
    )

    return {
        "score":      score,
        "n_signals":  n_signals,
        "bias":       bias,
        "conf_pct":   conf_pct,
        "conf_label": conf_label,
        "pcr_oi":     pcr_oi,
        "spot":       spot,
        "call_wall":  call_wall,
        "put_wall":   put_wall,
        "max_pain":   max_pain,
        "flow_dom":   dom,
        "summary":    summary,
    }


# ─── Price momentum snapshot ──────────────────────────────────────────────────

async def _price_snapshot(session: AsyncSession, symbol: str, minutes: int) -> dict | None:
    """
    Return (current_price, prev_price, support, resistance) for the last
    `minutes` window.  Used only for momentum / rangebound checks.
    """
    now   = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes)

    latest_ts = (
        await session.execute(
            select(func.max(ChainSnapshot.timestamp))
            .where(ChainSnapshot.symbol == symbol)
        )
    ).scalar()
    if not latest_ts:
        return None

    start_ts = (
        await session.execute(
            select(func.max(ChainSnapshot.timestamp))
            .where(ChainSnapshot.symbol == symbol,
                   ChainSnapshot.timestamp <= start)
        )
    ).scalar() or latest_ts

    latest_row = (
        await session.execute(
            select(ChainSnapshot)
            .where(ChainSnapshot.symbol == symbol,
                   ChainSnapshot.timestamp == latest_ts)
            .limit(1)
        )
    ).scalars().first()
    if not latest_row:
        return None

    start_row = (
        await session.execute(
            select(ChainSnapshot)
            .where(ChainSnapshot.symbol == symbol,
                   ChainSnapshot.timestamp == start_ts)
            .limit(1)
        )
    ).scalars().first() or latest_row

    current_price = float(latest_row.underlying_price or 0)
    prev_price    = float(start_row.underlying_price  or 0)
    band          = current_price * 0.03

    all_latest = (
        await session.execute(
            select(ChainSnapshot)
            .where(ChainSnapshot.symbol == symbol,
                   ChainSnapshot.timestamp == latest_ts)
        )
    ).scalars().all()

    support = resistance = None
    if all_latest and current_price > 0 and band > 0:
        put_rows  = [r for r in all_latest
                     if float(r.strike) <= current_price
                     and abs(float(r.strike) - current_price) <= band]
        call_rows = [r for r in all_latest
                     if float(r.strike) >= current_price
                     and abs(float(r.strike) - current_price) <= band]
        if put_rows:
            support    = float(max(put_rows,  key=lambda r: r.put_oi).strike)
        if call_rows:
            resistance = float(max(call_rows, key=lambda r: r.call_oi).strike)

    return {
        "current_price": current_price,
        "prev_price":    prev_price,
        "support":       support,
        "resistance":    resistance,
        "pct_move":      abs(current_price - prev_price) / prev_price if prev_price > 0 else 0,
        "price_up":      current_price > prev_price,
        "price_down":    current_price < prev_price,
    }


# ─── Aligned signal generation ────────────────────────────────────────────────

def _make_signal(
    symbol: str,
    sentiment: dict,
    snap5: dict | None,
    snap30: dict | None,
    snap60: dict | None,
) -> TradingSignal:
    """
    Produce a TradingSignal aligned with Market Sentiment.

    Rules:
    1. Rangebound (< 0.15% move in 30 min): always WAIT.
    2. sentiment BULLISH + 5m price up + conf >= 60%: Buy CE.
    3. sentiment BEARISH + 5m price down + conf >= 60%: Buy PE.
    4. Sentiment BULLISH/BEARISH but price not moving yet: WAIT (explaining why).
    5. Neutral sentiment: WAIT.
    """
    bias     = sentiment["bias"]
    conf_pct = sentiment["conf_pct"]
    score    = sentiment["score"]
    n_sig    = sentiment["n_signals"]
    pcr_oi   = sentiment["pcr_oi"]
    dom      = sentiment["flow_dom"]

    support    = (snap60 or snap30 or snap5 or {}).get("support")
    resistance = (snap60 or snap30 or snap5 or {}).get("resistance")

    # Derive display biases per timeframe from price direction vs sentiment
    def _tf_bias(snap: dict | None) -> Bias:
        if snap is None:
            return Bias.NEUTRAL
        if bias == Bias.BULLISH and snap["price_up"]:
            return Bias.BULLISH
        if bias == Bias.BEARISH and snap["price_down"]:
            return Bias.BEARISH
        return Bias.NEUTRAL

    b5  = _tf_bias(snap5)
    b30 = _tf_bias(snap30)
    b60 = bias  # 60 m aligns with overall sentiment direction

    def _wait(reason: str) -> TradingSignal:
        return TradingSignal(
            symbol=symbol, signal=Signal.WAIT, confidence=conf_pct,
            support=support, resistance=resistance,
            bias_5m=b5, bias_30m=b30, bias_60m=b60,
            reason=reason,
        )

    # ── 1. Rangebound guard ──────────────────────────────────────────────────
    if snap30 and snap30["pct_move"] < 0.0015:
        return _wait(
            f"Market rangebound (< 0.15% move in 30 min). "
            f"Sentiment {bias.value} but no directional price move. Wait."
        )

    # ── 2. Stable time move: 5m/30m/60m all same direction ────────────────────
    stable_up = (
        snap5 and snap5["price_up"]
        and (not snap30 or snap30["price_up"])
        and (not snap60 or snap60["price_up"])
    )
    stable_down = (
        snap5 and snap5["price_down"]
        and (not snap30 or snap30["price_down"])
        and (not snap60 or snap60["price_down"])
    )

    pcr_str  = f"PCR {pcr_oi:.2f}"
    dom_str  = dom.replace("_", " ").title() if dom else "mixed flow"
    score_str = f"score {score}/{n_sig * 2 if n_sig else '?'}"

    # ── 3. Buy CE (stable uptrend) ────────────────────────────────────────────
    if bias == Bias.BULLISH and stable_up and conf_pct >= 60:
        reason = (
            f"Stable uptrend ({score_str}): {pcr_str}, {dom_str}. "
            f"5m/30m/60m price aligned upward."
        )
        return TradingSignal(
            symbol=symbol, signal=Signal.BUY_CE,
            confidence=min(conf_pct + 10, 95),
            support=support, resistance=resistance,
            bias_5m=Bias.BULLISH, bias_30m=b30, bias_60m=Bias.BULLISH,
            reason=reason,
        )

    # ── 4. Buy PE (stable downtrend) ──────────────────────────────────────────
    if bias == Bias.BEARISH and stable_down and conf_pct >= 60:
        reason = (
            f"Stable downtrend ({score_str}): {pcr_str}, {dom_str}. "
            f"5m/30m/60m price aligned downward."
        )
        return TradingSignal(
            symbol=symbol, signal=Signal.BUY_PE,
            confidence=min(conf_pct + 10, 95),
            support=support, resistance=resistance,
            bias_5m=Bias.BEARISH, bias_30m=b30, bias_60m=Bias.BEARISH,
            reason=reason,
        )

    # ── 5. Wait with informative reason ──────────────────────────────────────
    if bias == Bias.BULLISH:
        reason = (
            f"Sentiment Bullish ({score_str}, {pcr_str}) "
            f"but need 5m/30m/60m aligned upward for stable move. Wait for momentum."
        )
    elif bias == Bias.BEARISH:
        reason = (
            f"Sentiment Bearish ({score_str}, {pcr_str}) "
            f"but need 5m/30m/60m aligned downward for stable move. Wait for momentum."
        )
    else:
        reason = (
            f"Mixed signals ({score_str}, {pcr_str}, {dom_str}). "
            f"No clear directional consensus — wait."
        )

    return _wait(reason)


# ─── Main cycle ───────────────────────────────────────────────────────────────

async def run_signal_engine_cycle() -> None:
    """
    Run once per collector cycle:
    1. Compute Market-Sentiment-aligned score for each symbol.
    2. Build price momentum snapshots.
    3. Generate and persist a TradingSignal.
    """
    async with AsyncSessionLocal() as session:
        for symbol in settings.supported_symbols:
            try:
                # Same analytics stack as Market Sentiment
                sentiment = await _compute_sentiment(session, symbol)

                # Price momentum windows
                snap5  = await _price_snapshot(session, symbol, 5)
                snap30 = await _price_snapshot(session, symbol, 30)
                snap60 = await _price_snapshot(session, symbol, 60)

                f5_views = await _latest_feature_views(session, symbol, "5m", limit=2)
                f30_views = await _latest_feature_views(session, symbol, "30m", limit=2)
                f60_views = await _latest_feature_views(session, symbol, "60m", limit=2)
                long_context = None

                if f5_views and f30_views and f60_views:
                    previous_views = None
                    if len(f5_views) > 1 and len(f30_views) > 1 and len(f60_views) > 1:
                        previous_views = (f5_views[1], f30_views[1], f60_views[1])
                    current_reference_time = f5_views[0].snapshot_timestamp or datetime.now(timezone.utc)
                    long_context = await load_long_signal_context(session, symbol, current_reference_time)
                    ts = generate_main_signal_from_features(
                        symbol,
                        (f5_views[0], f30_views[0], f60_views[0]),
                        previous_views,
                        context=long_context,
                    )
                else:
                    ts = _make_signal(symbol, sentiment, snap5, snap30, snap60)

                latest_existing = (
                    await session.execute(
                        select(TradingSignalRow)
                        .where(TradingSignalRow.symbol == symbol)
                        .order_by(TradingSignalRow.generated_at.desc())
                        .limit(1)
                    )
                ).scalars().first()

                generated_at = datetime.now(timezone.utc)
                entry_price = None
                if f5_views:
                    entry_price = float(f5_views[0].current_price)
                elif snap5:
                    entry_price = float(snap5["current_price"])
                elif snap30:
                    entry_price = float(snap30["current_price"])
                elif sentiment.get("spot"):
                    entry_price = float(sentiment["spot"])

                managed_hard_exit = False
                managed_hard_exit_reason = None
                managed_entry_gate_reason = None
                managed_base_signal = ts.signal.value
                managed_success_threshold = None
                managed_stop_points = None
                open_main_trade_row = await get_open_trade_row(session, engine="MAIN", symbol=symbol)
                open_main_trade = trade_state_from_row(open_main_trade_row)
                if f5_views and f30_views and f60_views:
                    current_f5 = f5_views[0]
                    current_f30 = f30_views[0]
                    current_f60 = f60_views[0]
                    if any(
                        feature.trap_warning_flag
                        for feature in (current_f5, current_f30, current_f60)
                    ):
                        managed_hard_exit = True
                        managed_hard_exit_reason = "Higher-timeframe trap risk is confirmed. Exit the active trade."
                    elif (
                        current_f30.price_rangebound
                        and current_f60.price_rangebound
                        and int(ts.confidence) < 45
                    ):
                        managed_hard_exit = True
                        managed_hard_exit_reason = "30m and 60m both slipped back into rangebound conditions."
                    if not managed_hard_exit:
                        long_outlook = determine_main_outlook(
                            (current_f5, current_f30, current_f60),
                            long_context,
                        )
                        management_plan = derive_main_trade_management_plan(
                            open_trade=open_main_trade,
                            current_features=(current_f5, current_f30, current_f60),
                            long_context=long_context,
                            outlook=long_outlook,
                            confidence=int(ts.confidence),
                            current_price=entry_price,
                        )
                        if management_plan.base_signal_override is not None:
                            managed_base_signal = management_plan.base_signal_override
                        if management_plan.hard_exit:
                            managed_hard_exit = True
                            managed_hard_exit_reason = management_plan.hard_exit_reason
                if long_context is not None:
                    managed_success_threshold, managed_stop_points = scale_trade_thresholds(
                        base_success=success_threshold_points("MAIN", symbol),
                        base_stop=stop_threshold_points("MAIN", symbol),
                        volatility_ratio=long_context.intraday_volatility_ratio,
                        event_risk=long_context.event_profile in {"event", "event_expiry", "expiry"},
                    )
                    if open_main_trade is None and managed_base_signal in {"Buy CE", "Buy PE"}:
                        if long_context.session_bucket == "MIDDAY" and int(ts.confidence) < 88:
                            managed_entry_gate_reason = (
                                "Entry blocked: midday structure is still noisy for fresh long entries."
                            )
                        elif (
                            long_context.intraday_volatility_ratio is not None
                            and long_context.intraday_volatility_ratio < 0.82
                            and int(ts.confidence) < 90
                        ):
                            managed_entry_gate_reason = (
                                "Entry blocked: intraday volatility is too compressed for a clean long setup."
                            )
                        elif (
                            long_context.intraday_volatility_ratio is not None
                            and long_context.intraday_volatility_ratio > 1.8
                            and int(ts.confidence) < 90
                        ):
                            managed_entry_gate_reason = (
                                "Entry blocked: tape is hyper-volatile; waiting for cleaner continuation."
                            )
                        elif long_context.breadth_available:
                            if (
                                managed_base_signal == "Buy CE"
                                and not (
                                    long_context.breadth_direction == "bullish"
                                    and int(long_context.breadth_score or 0) >= 18
                                )
                            ):
                                managed_entry_gate_reason = (
                                    "Entry blocked: internal breadth is not confirming the bullish setup."
                                )
                            elif (
                                managed_base_signal == "Buy PE"
                                and not (
                                    long_context.breadth_direction == "bearish"
                                    and int(long_context.breadth_score or 0) <= -18
                                )
                            ):
                                managed_entry_gate_reason = (
                                    "Entry blocked: internal breadth is not confirming the bearish setup."
                                )

                managed_decision, _managed_trade_row = await apply_managed_trade_decision(
                    session,
                    engine="MAIN",
                    symbol=symbol,
                    base_signal=managed_base_signal,
                    confidence=int(ts.confidence),
                    current_price=entry_price,
                    reason=ts.reason,
                    now_utc=generated_at,
                    hard_exit=managed_hard_exit,
                    hard_exit_reason=managed_hard_exit_reason,
                    success_threshold_override=managed_success_threshold,
                    stop_points_override=managed_stop_points,
                    signal_version="main_v4_live",
                    entry_gate_reason=managed_entry_gate_reason,
                )
                public_signal = managed_decision.public_signal
                public_reason = (
                    managed_decision.management_reason
                    if (
                        managed_decision.action in {"hold", "exit"}
                        or (managed_decision.action == "wait" and managed_base_signal in {"Buy CE", "Buy PE"})
                    )
                    else ts.reason
                )
                stored_reason = fit_trading_signal_reason(public_reason)

                row = TradingSignalRow(
                    symbol=symbol,
                    signal=public_signal,
                    confidence=ts.confidence,
                    support=ts.support,
                    resistance=ts.resistance,
                    bias_5m=ts.bias_5m.value,
                    bias_30m=ts.bias_30m.value,
                    bias_60m=ts.bias_60m.value,
                    reason=stored_reason,
                )
                session.add(row)

                context = derive_signal_context(
                    public_signal,
                    ts.bias_5m.value,
                    ts.bias_30m.value,
                    ts.bias_60m.value,
                    int(ts.confidence),
                )

                breakout = False
                breakdown = False
                trap_detected = False
                rangebound = False
                five_min_change_points = None
                call_oi_delta = None
                put_oi_delta = None
                writer_support = False
                previous_support = None
                previous_resistance = None
                if f5_views and f30_views and f60_views:
                    current_f5 = f5_views[0]
                    current_f30 = f30_views[0]
                    current_f60 = f60_views[0]
                    breakout = bool(current_f5.breakout_flag or current_f30.breakout_flag)
                    breakdown = bool(current_f5.breakdown_flag or current_f30.breakdown_flag)
                    trap_detected = bool(
                        current_f5.trap_warning_flag
                        or current_f30.trap_warning_flag
                        or current_f60.trap_warning_flag
                    )
                    rangebound = bool(
                        current_f30.price_rangebound
                        and current_f60.price_rangebound
                    )
                    five_min_change_points = round(current_f5.current_price - current_f5.prev_price, 2)
                    call_oi_delta = float(current_f5.near_resistance_call_oi_change)
                    put_oi_delta = float(current_f5.near_support_put_oi_change)
                    if ts.signal.value == "Buy CE":
                        writer_support = bool(current_f30.writer_bullish_score or current_f60.writer_bullish_score)
                    elif ts.signal.value == "Buy PE":
                        writer_support = bool(current_f30.writer_bearish_score or current_f60.writer_bearish_score)
                    if len(f30_views) > 1:
                        previous_support = f30_views[1].support_strike
                        previous_resistance = f30_views[1].resistance_strike
                    elif len(f60_views) > 1:
                        previous_support = f60_views[1].support_strike
                        previous_resistance = f60_views[1].resistance_strike

                quant_context = await build_quant_context(
                    session,
                    symbol=symbol,
                    engine="MAIN",
                    signal=public_signal,
                    entry_time=generated_at,
                    current_price=entry_price,
                    support=ts.support,
                    resistance=ts.resistance,
                    five_min_change_points=five_min_change_points,
                    breakout=breakout,
                    breakdown=breakdown,
                    trap_detected=trap_detected,
                    rangebound=rangebound,
                    call_oi_delta=call_oi_delta,
                    put_oi_delta=put_oi_delta,
                    volume_spike=bool(f5_views and f5_views[0].volume_spike),
                    writer_support=writer_support,
                    outlook=str(context["outlook"]),
                    state=str(context["state"]),
                    entry_ready=bool(context["entry_ready"]),
                    previous_support=previous_support,
                    previous_resistance=previous_resistance,
                )
                await record_shadow_decision(
                    session,
                    engine="MAIN",
                    signal_version="main_v4_live",
                    mode="LIVE",
                    symbol=symbol,
                    signal=public_signal,
                    confidence=int(ts.confidence),
                    generated_at=generated_at,
                    reason=public_reason,
                    context=quant_context,
                    outlook=str(context["outlook"]),
                    state=str(context["state"]),
                    entry_ready=bool(context["entry_ready"]),
                )
                shadow_signal, shadow_confidence, shadow_reason = derive_shadow_signal(
                    engine="MAIN",
                    signal=public_signal,
                    confidence=int(ts.confidence),
                    context=quant_context,
                    entry_ready=bool(context["entry_ready"]),
                )
                await record_shadow_decision(
                    session,
                    engine="MAIN",
                    signal_version="main_v4_shadow",
                    mode="SHADOW",
                    symbol=symbol,
                    signal=shadow_signal,
                    confidence=shadow_confidence,
                    generated_at=generated_at,
                    reason=shadow_reason,
                    context=quant_context,
                    outlook=str(context["outlook"]),
                    state=str(context["state"]),
                    entry_ready=shadow_signal in ("Buy CE", "Buy PE"),
                )
                signal_changed = (
                    latest_existing is None
                    or latest_existing.signal != public_signal
                )
                if managed_decision.action == "entry" and public_signal in ("Buy CE", "Buy PE") and signal_changed:
                    if entry_price is not None and entry_price > 0:
                        await record_signal_outcome_candidate(
                            session,
                            engine="MAIN",
                            symbol=symbol,
                            signal=public_signal,
                            confidence=int(ts.confidence),
                            entry_price=entry_price,
                            entry_time=generated_at,
                            reason=public_reason,
                            outlook=str(context["outlook"]),
                            state=str(context["state"]),
                        )
                        await record_quant_signal_candidate(
                            session,
                            engine="MAIN",
                            signal_version="main_v4_live",
                            symbol=symbol,
                            signal=public_signal,
                            confidence=int(ts.confidence),
                            entry_time=generated_at,
                            underlying_entry_price=entry_price,
                            reason=public_reason,
                            context=quant_context,
                            outlook=str(context["outlook"]),
                            state=str(context["state"]),
                            entry_ready=bool(context["entry_ready"]),
                        )

                if shadow_signal in ("Buy CE", "Buy PE") and entry_price is not None and entry_price > 0:
                    await record_quant_signal_candidate(
                        session,
                        engine="MAIN",
                        signal_version="main_v4_shadow",
                        symbol=symbol,
                        signal=shadow_signal,
                        confidence=shadow_confidence,
                        entry_time=generated_at,
                        underlying_entry_price=entry_price,
                        reason=shadow_reason,
                        context=quant_context,
                        outlook=str(context["outlook"]),
                        state=str(context["state"]),
                        entry_ready=True,
                    )

                logger.info(
                    "signal_generated",
                    symbol=symbol,
                    signal=public_signal,
                    confidence=ts.confidence,
                    sentiment=sentiment["bias"].value,
                    pcr_oi=round(sentiment["pcr_oi"], 3),
                    score=f"{sentiment['score']}/{sentiment['n_signals'] * 2}",
                )

            except Exception as exc:
                logger.warning("signal_engine_cycle_failed",
                               symbol=symbol, error=str(exc))

        await refresh_pending_signal_outcomes(session)
        await refresh_pending_quant_signal_outcomes(session)
        await session.commit()
