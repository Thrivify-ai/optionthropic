"""
Quick signal engine for fast intraday directional moves.

Phase 2 adds:
- session-aware thresholds
- reward/risk gating
- confidence scoring
- shared lifecycle state (candidate -> active -> cooldown)

The API contract stays backward compatible. The response still exposes
`quick_signal`, but now also includes lifecycle metadata so the frontend can
explain why a signal is active, forming, or cooling down.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.quick_signal_phase2 import (
    BUY_SIGNALS,
    QuickSignalSessionProfile,
    adjusted_threshold,
    apply_lifecycle,
    parse_lifecycle_state,
    quick_signal_confidence,
    reward_risk_ok,
    serialize_lifecycle_state,
    session_profile_for,
)
from app.analytics.quick_signal_utils import (
    has_directional_persistence,
    is_quick_rangebound,
)
from app.logging_config import get_logger
from app.models.chain_snapshot import ChainSnapshot
from app.services.runtime_cache import runtime_cache

logger = get_logger(__name__)


_SYMBOL_CONFIG: dict[str, dict[str, float]] = {
    "NIFTY": {
        "bull_mom": 18,
        "bear_mom": -18,
        "mom_3m": 12,
        "soft_ratio": 0.5,
        "pct_min": 0.0006,
        "band_pct": 0.020,
        "target_move": 35,
    },
    "BANKNIFTY": {
        "bull_mom": 45,
        "bear_mom": -45,
        "mom_3m": 30,
        "soft_ratio": 0.5,
        "pct_min": 0.0006,
        "band_pct": 0.020,
        "target_move": 80,
    },
    "SENSEX": {
        "bull_mom": 30,
        "bear_mom": -30,
        "mom_3m": 22,
        "soft_ratio": 0.5,
        "pct_min": 0.0004,
        "band_pct": 0.015,
        "target_move": 100,
    },
}
_DEFAULT_CONFIG: dict[str, float] = {
    "bull_mom": 22,
    "bear_mom": -22,
    "mom_3m": 15,
    "soft_ratio": 0.5,
    "pct_min": 0.0006,
    "band_pct": 0.020,
    "target_move": 40,
}

_VOLUME_SPIKE_RATIO = 1.5
_QUICK_SIGNAL_STATE_TTL_SECONDS = 1800


def _cfg(symbol: str) -> dict[str, float]:
    return _SYMBOL_CONFIG.get(symbol.upper(), _DEFAULT_CONFIG)


def _state_key(symbol: str) -> str:
    return f"quick-signal:lifecycle:{symbol.upper()}:v2"


def _timestamp_now(now_utc: datetime | None = None) -> str:
    return (now_utc or datetime.now(timezone.utc)).isoformat()


def _wait_payload(
    symbol: str,
    reason: str,
    *,
    now_utc: datetime,
    support: Optional[float] = None,
    resistance: Optional[float] = None,
    current_price: Optional[float] = None,
    momentum: Optional[float] = None,
    momentum_3m: Optional[float] = None,
    volume_spike: bool = False,
    breakout: bool = False,
    breakdown: bool = False,
    oi_confirmed: bool = False,
    confidence: int = 0,
    raw_signal: str = "Wait",
    risk_reward_ok_flag: bool = False,
    risk_reward_reason: str = "No trade direction",
    trap_detected: bool = False,
    rangebound: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": symbol,
        "quick_signal": "Wait",
        "raw_signal": raw_signal,
        "momentum": momentum,
        "momentum_3m": momentum_3m,
        "volume_spike": bool(volume_spike),
        "breakout": bool(breakout),
        "breakdown": bool(breakdown),
        "oi_confirmed": bool(oi_confirmed),
        "support": support,
        "resistance": resistance,
        "reason": reason,
        "confidence": int(confidence),
        "risk_reward_ok": bool(risk_reward_ok_flag),
        "risk_reward_reason": risk_reward_reason,
        "trap_detected": bool(trap_detected),
        "rangebound": bool(rangebound),
        "timestamp": _timestamp_now(now_utc),
    }
    if current_price is not None:
        payload["current_price"] = round(current_price, 2)
    return payload


def _compose_reason(engine_reason: str, state_reason: str) -> str:
    if not engine_reason:
        return state_reason
    if not state_reason or state_reason == engine_reason:
        return engine_reason
    return f"{engine_reason} | {state_reason}"


async def _finalize_payload(
    symbol: str,
    payload: dict[str, Any],
    *,
    profile: QuickSignalSessionProfile,
    now_utc: datetime,
    hard_invalidation: bool,
) -> dict[str, Any]:
    cached_state = await runtime_cache.get_json(_state_key(symbol))
    previous = parse_lifecycle_state(cached_state if isinstance(cached_state, dict) else None)

    raw_signal = payload.get("raw_signal") or payload.get("quick_signal") or "Wait"
    confidence = int(payload.get("confidence", 0) or 0)

    lifecycle_state, lifecycle_payload = apply_lifecycle(
        previous,
        raw_signal=raw_signal,
        confidence=confidence,
        now_utc=now_utc,
        profile=profile,
        hard_invalidation=hard_invalidation,
    )

    ttl_seconds = max(
        _QUICK_SIGNAL_STATE_TTL_SECONDS,
        profile.min_hold_seconds + profile.cooldown_seconds + 300,
    )
    await runtime_cache.set_json(
        _state_key(symbol),
        serialize_lifecycle_state(lifecycle_state),
        ttl_seconds,
    )

    payload.update(lifecycle_payload)
    payload["raw_signal"] = raw_signal
    payload["confidence"] = confidence
    payload["session"] = profile.name
    payload["reason"] = _compose_reason(payload.get("reason", ""), lifecycle_payload["state_reason"])
    payload["timestamp"] = _timestamp_now(now_utc)
    return payload


async def _latest_timestamps(session: AsyncSession, symbol: str, n: int = 7) -> list:
    rows = (
        await session.execute(
            select(func.distinct(ChainSnapshot.timestamp))
            .where(ChainSnapshot.symbol == symbol)
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(n)
        )
    ).scalars().all()
    return sorted(rows, reverse=True)


async def _snap(session: AsyncSession, symbol: str, ts) -> Optional[dict[str, float]]:
    price = (
        await session.execute(
            select(ChainSnapshot.underlying_price)
            .where(ChainSnapshot.symbol == symbol, ChainSnapshot.timestamp == ts)
            .limit(1)
        )
    ).scalar()
    if price is None:
        return None

    agg = (
        await session.execute(
            select(
                func.sum(ChainSnapshot.call_oi),
                func.sum(ChainSnapshot.put_oi),
                func.sum(ChainSnapshot.call_volume),
                func.sum(ChainSnapshot.put_volume),
            ).where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp == ts,
            )
        )
    ).one_or_none()
    if agg is None:
        return None

    total_vol = float((agg[2] or 0) + (agg[3] or 0))
    return {
        "price": float(price),
        "call_oi": float(agg[0] or 0),
        "put_oi": float(agg[1] or 0),
        "call_volume": float(agg[2] or 0),
        "put_volume": float(agg[3] or 0),
        "total_vol": total_vol,
    }


async def _support_resistance(
    session: AsyncSession,
    symbol: str,
    ts,
    spot: float,
    band_pct: float,
) -> tuple[Optional[float], Optional[float]]:
    band = spot * band_pct
    rows = (
        await session.execute(
            select(ChainSnapshot).where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp == ts,
            )
        )
    ).scalars().all()

    support = resistance = None
    if rows and spot > 0 and band > 0:
        below = [
            row
            for row in rows
            if float(row.strike) <= spot and abs(float(row.strike) - spot) <= band
        ]
        above = [
            row
            for row in rows
            if float(row.strike) >= spot and abs(float(row.strike) - spot) <= band
        ]
        if below:
            support = float(max(below, key=lambda row: row.put_oi).strike)
        if above:
            resistance = float(max(above, key=lambda row: row.call_oi).strike)
    return support, resistance


def _target_move(cfg: dict[str, float]) -> int:
    return int(cfg.get("target_move", 40))


def _signal_payload(
    symbol: str,
    signal: str,
    *,
    now_utc: datetime,
    momentum_1m: float,
    momentum_3m: float | None,
    volume_spike: bool,
    breakout: bool,
    breakdown: bool,
    oi_confirmed: bool,
    support: float | None,
    resistance: float | None,
    spot: float,
    target_move: int,
    confidence: int,
    risk_reward_ok_flag: bool,
    risk_reward_reason: str,
    trap_detected: bool,
    rangebound: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "quick_signal": signal,
        "raw_signal": signal,
        "momentum": momentum_1m,
        "momentum_3m": momentum_3m,
        "volume_spike": bool(volume_spike),
        "breakout": bool(breakout),
        "breakdown": bool(breakdown),
        "oi_confirmed": bool(oi_confirmed),
        "support": support,
        "resistance": resistance,
        "current_price": round(spot, 2),
        "target_move_points": target_move,
        "confidence": int(confidence),
        "risk_reward_ok": bool(risk_reward_ok_flag),
        "risk_reward_reason": risk_reward_reason,
        "trap_detected": bool(trap_detected),
        "rangebound": bool(rangebound),
        "reason": reason,
        "timestamp": _timestamp_now(now_utc),
    }


async def run_quick_signal_engine(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """
    Quick signal engine with session-aware thresholds and lifecycle control.

    Returns a dict with `quick_signal` in {"Buy CE", "Buy PE", "Wait"}.
    """
    symbol = symbol.upper()
    cfg = _cfg(symbol)
    now_utc = datetime.now(timezone.utc)
    profile = session_profile_for(now_utc)

    if profile.name == "closed":
        payload = _wait_payload(
            symbol,
            "Market is closed; quick signals stay paused until the next session.",
            now_utc=now_utc,
        )
        return await _finalize_payload(
            symbol,
            payload,
            profile=profile,
            now_utc=now_utc,
            hard_invalidation=False,
        )

    bull_mom = adjusted_threshold(cfg["bull_mom"], profile)
    bear_mom = -adjusted_threshold(abs(cfg["bear_mom"]), profile)
    mom_3m_thresh = adjusted_threshold(cfg["mom_3m"], profile)
    pct_min = cfg["pct_min"] * profile.threshold_multiplier * 100
    soft_ratio = float(cfg.get("soft_ratio", 0.5))
    target_move = _target_move(cfg)

    timestamps = await _latest_timestamps(session, symbol, n=7)
    if len(timestamps) < 2:
        payload = _wait_payload(
            symbol,
            "Insufficient data (need at least 2 snapshots).",
            now_utc=now_utc,
        )
        return await _finalize_payload(
            symbol,
            payload,
            profile=profile,
            now_utc=now_utc,
            hard_invalidation=False,
        )

    ts_now = timestamps[0]
    ts_1m = next(
        (ts for ts in timestamps[1:] if (ts_now - ts).total_seconds() >= 40),
        timestamps[1],
    )
    ts_3m = next(
        (ts for ts in timestamps[1:] if (ts_now - ts).total_seconds() >= 100),
        None,
    )

    curr = await _snap(session, symbol, ts_now)
    if not curr or curr["price"] == 0:
        payload = _wait_payload(
            symbol,
            "No current price data.",
            now_utc=now_utc,
            current_price=curr["price"] if curr else None,
        )
        return await _finalize_payload(
            symbol,
            payload,
            profile=profile,
            now_utc=now_utc,
            hard_invalidation=False,
        )

    prev_1m = await _snap(session, symbol, ts_1m)
    if not prev_1m:
        payload = _wait_payload(
            symbol,
            "Cannot read the prior minute snapshot.",
            now_utc=now_utc,
            current_price=curr["price"],
        )
        return await _finalize_payload(
            symbol,
            payload,
            profile=profile,
            now_utc=now_utc,
            hard_invalidation=False,
        )

    spot = curr["price"]
    support, resistance = await _support_resistance(
        session,
        symbol,
        ts_now,
        spot,
        cfg["band_pct"],
    )

    momentum_1m = round(spot - prev_1m["price"], 2)
    pct_1m = (momentum_1m / prev_1m["price"] * 100) if prev_1m["price"] else 0.0
    soft_bull = momentum_1m >= bull_mom * soft_ratio or pct_1m >= pct_min
    soft_bear = momentum_1m <= bear_mom * soft_ratio or pct_1m <= -pct_min
    strong_bullish = momentum_1m >= bull_mom or (pct_1m >= pct_min and momentum_1m > 0)
    strong_bearish = momentum_1m <= bear_mom or (pct_1m <= -pct_min and momentum_1m < 0)

    minute_vols: list[float] = []
    for idx in range(min(5, len(timestamps) - 1)):
        newer = await _snap(session, symbol, timestamps[idx])
        older = await _snap(session, symbol, timestamps[idx + 1])
        if newer and older:
            delta = newer["total_vol"] - older["total_vol"]
            if delta > 0:
                minute_vols.append(delta)

    current_min_vol = max(0.0, curr["total_vol"] - prev_1m["total_vol"])
    avg_min_vol = sum(minute_vols) / len(minute_vols) if minute_vols else 0.0
    volume_spike = avg_min_vol > 0 and current_min_vol >= _VOLUME_SPIKE_RATIO * avg_min_vol

    bullish_breakout = resistance is not None and spot > resistance * 1.001
    bearish_breakdown = support is not None and spot < support * 0.999

    call_oi_delta = curr["call_oi"] - prev_1m["call_oi"]
    put_oi_delta = curr["put_oi"] - prev_1m["put_oi"]
    oi_bullish = call_oi_delta < 0 and put_oi_delta >= 0
    oi_bearish = put_oi_delta < 0 and call_oi_delta >= 0

    trap_bull = (
        bullish_breakout
        and resistance is not None
        and prev_1m["price"] > resistance
        and spot < prev_1m["price"]
    )
    trap_bear = (
        bearish_breakdown
        and support is not None
        and prev_1m["price"] < support
        and spot > prev_1m["price"]
    )

    momentum_3m = None
    momentum_prev_leg = None
    if ts_3m is not None:
        prev_3m = await _snap(session, symbol, ts_3m)
        if prev_3m and prev_3m["price"]:
            momentum_3m = round(spot - prev_3m["price"], 2)
            momentum_prev_leg = round(prev_1m["price"] - prev_3m["price"], 2)

    trap_bull = trap_bull or (
        resistance is not None
        and prev_1m["price"] > resistance * 1.001
        and spot < resistance
    )
    trap_bear = trap_bear or (
        support is not None
        and prev_1m["price"] < support * 0.999
        and spot > support
    )

    strong_bullish_3m = momentum_3m is not None and momentum_3m >= mom_3m_thresh
    strong_bearish_3m = momentum_3m is not None and momentum_3m <= -mom_3m_thresh

    rangebound = is_quick_rangebound(
        spot,
        support,
        resistance,
        momentum_1m,
        momentum_3m,
        bull_mom,
        mom_3m_thresh,
    )
    hard_invalidation = bool(trap_bull or trap_bear or rangebound)

    bullish_trend_ok = (
        (strong_bullish and (momentum_3m is None or momentum_3m > 0))
        or (strong_bullish_3m and momentum_1m > 0)
    )
    bearish_trend_ok = (
        (strong_bearish and (momentum_3m is None or momentum_3m < 0))
        or (strong_bearish_3m and momentum_1m < 0)
    )

    has_bull_conf = bullish_breakout or volume_spike or oi_bullish
    has_bear_conf = bearish_breakdown or volume_spike or oi_bearish
    soft_bull_ok = soft_bull and (momentum_3m is None or momentum_3m > 0) and has_bull_conf
    soft_bear_ok = soft_bear and (momentum_3m is None or momentum_3m < 0) and has_bear_conf

    bullish_persistent = has_directional_persistence(
        momentum_1m,
        momentum_prev_leg,
        "bullish",
    )
    bearish_persistent = has_directional_persistence(
        momentum_1m,
        momentum_prev_leg,
        "bearish",
    )

    bullish_ready = (bullish_trend_ok or soft_bull_ok) and bullish_persistent and not trap_bull
    bearish_ready = (bearish_trend_ok or soft_bear_ok) and bearish_persistent and not trap_bear

    bullish_rr_ok, bullish_rr_reason = reward_risk_ok(
        "Buy CE",
        spot=spot,
        support=support,
        resistance=resistance,
        target_move=target_move,
        breakout=bullish_breakout,
        breakdown=False,
    )
    bearish_rr_ok, bearish_rr_reason = reward_risk_ok(
        "Buy PE",
        spot=spot,
        support=support,
        resistance=resistance,
        target_move=target_move,
        breakout=False,
        breakdown=bearish_breakdown,
    )

    bullish_confidence = quick_signal_confidence(
        bullish=True,
        bearish=False,
        strong_1m=strong_bullish,
        strong_3m=strong_bullish_3m,
        breakout=bullish_breakout,
        breakdown=False,
        volume_spike=volume_spike,
        oi_confirmed=oi_bullish,
        persistent=bullish_persistent,
        trap=trap_bull,
        rangebound=rangebound,
        risk_reward_ok=bullish_rr_ok,
    )
    bearish_confidence = quick_signal_confidence(
        bullish=False,
        bearish=True,
        strong_1m=strong_bearish,
        strong_3m=strong_bearish_3m,
        breakout=False,
        breakdown=bearish_breakdown,
        volume_spike=volume_spike,
        oi_confirmed=oi_bearish,
        persistent=bearish_persistent,
        trap=trap_bear,
        rangebound=rangebound,
        risk_reward_ok=bearish_rr_ok,
    )

    bullish_live = bullish_ready and bullish_rr_ok and bullish_confidence >= profile.min_confidence
    bearish_live = bearish_ready and bearish_rr_ok and bearish_confidence >= profile.min_confidence

    if bullish_live and not bearish_live:
        ext: list[str] = []
        if bullish_breakout and resistance is not None:
            ext.append(f"breakout above {int(resistance):,}")
        if oi_bullish:
            ext.append("call covering with put support")
        if volume_spike:
            ext.append("volume expansion")
        ext.append(bullish_rr_reason)
        reason = (
            f"+{momentum_1m:.0f} pts in 1m"
            + (f", +{momentum_3m:.0f} pts in 3m" if momentum_3m is not None else "")
            + f" | {' | '.join(ext)} | targeting +{target_move} pts"
        )
        payload = _signal_payload(
            symbol,
            "Buy CE",
            now_utc=now_utc,
            momentum_1m=momentum_1m,
            momentum_3m=momentum_3m,
            volume_spike=volume_spike,
            breakout=bullish_breakout,
            breakdown=False,
            oi_confirmed=oi_bullish,
            support=support,
            resistance=resistance,
            spot=spot,
            target_move=target_move,
            confidence=bullish_confidence,
            risk_reward_ok_flag=bullish_rr_ok,
            risk_reward_reason=bullish_rr_reason,
            trap_detected=trap_bull,
            rangebound=rangebound,
            reason=reason,
        )
        return await _finalize_payload(
            symbol,
            payload,
            profile=profile,
            now_utc=now_utc,
            hard_invalidation=hard_invalidation,
        )

    if bearish_live and not bullish_live:
        ext = []
        if bearish_breakdown and support is not None:
            ext.append(f"breakdown below {int(support):,}")
        if oi_bearish:
            ext.append("put covering with call pressure")
        if volume_spike:
            ext.append("volume expansion")
        ext.append(bearish_rr_reason)
        reason = (
            f"{momentum_1m:.0f} pts in 1m"
            + (f", {momentum_3m:.0f} pts in 3m" if momentum_3m is not None else "")
            + f" | {' | '.join(ext)} | targeting -{target_move} pts"
        )
        payload = _signal_payload(
            symbol,
            "Buy PE",
            now_utc=now_utc,
            momentum_1m=momentum_1m,
            momentum_3m=momentum_3m,
            volume_spike=volume_spike,
            breakout=False,
            breakdown=bearish_breakdown,
            oi_confirmed=oi_bearish,
            support=support,
            resistance=resistance,
            spot=spot,
            target_move=target_move,
            confidence=bearish_confidence,
            risk_reward_ok_flag=bearish_rr_ok,
            risk_reward_reason=bearish_rr_reason,
            trap_detected=trap_bear,
            rangebound=rangebound,
            reason=reason,
        )
        return await _finalize_payload(
            symbol,
            payload,
            profile=profile,
            now_utc=now_utc,
            hard_invalidation=hard_invalidation,
        )

    if bullish_ready and bearish_ready:
        wait_reason = "Bullish and bearish intraday evidence conflict; waiting for cleaner direction."
        confidence = max(bullish_confidence, bearish_confidence)
        payload = _wait_payload(
            symbol,
            wait_reason,
            now_utc=now_utc,
            support=support,
            resistance=resistance,
            current_price=spot,
            momentum=momentum_1m,
            momentum_3m=momentum_3m,
            volume_spike=volume_spike,
            breakout=bullish_breakout,
            breakdown=bearish_breakdown,
            oi_confirmed=False,
            confidence=confidence,
            risk_reward_ok_flag=False,
            risk_reward_reason="Conflicting direction",
            trap_detected=hard_invalidation,
            rangebound=rangebound,
        )
        return await _finalize_payload(
            symbol,
            payload,
            profile=profile,
            now_utc=now_utc,
            hard_invalidation=hard_invalidation,
        )

    wait_reasons: list[str] = []
    confidence = max(bullish_confidence, bearish_confidence)
    rr_ok = bullish_rr_ok if bullish_ready else bearish_rr_ok if bearish_ready else False
    rr_reason = (
        bullish_rr_reason
        if bullish_ready
        else bearish_rr_reason
        if bearish_ready
        else "No qualified setup"
    )

    if hard_invalidation:
        if trap_bull or trap_bear:
            wait_reasons.append("trap risk is elevated after a failed move")
        if rangebound:
            wait_reasons.append("price is still rangebound inside support and resistance")
    elif bullish_ready or bearish_ready:
        if not rr_ok:
            wait_reasons.append(rr_reason)
        if confidence < profile.min_confidence:
            wait_reasons.append(
                f"confidence {confidence} is below the {profile.min_confidence} threshold for the {profile.name} session"
            )
    else:
        if not bullish_trend_ok and not bearish_trend_ok and not soft_bull_ok and not soft_bear_ok:
            msg = f"1m {momentum_1m:+.0f} pts vs threshold {bull_mom:.0f}"
            if momentum_3m is not None:
                msg += f"; 3m {momentum_3m:+.0f} pts vs threshold {mom_3m_thresh:.0f}"
            wait_reasons.append(f"momentum is below the required session-adjusted threshold ({msg})")
        elif (soft_bull and not has_bull_conf) or (soft_bear and not has_bear_conf):
            wait_reasons.append("momentum appeared, but breakout, volume, or OI confirmation is still missing")
        elif momentum_3m is not None and (
            (strong_bullish and momentum_3m <= 0)
            or (strong_bearish and momentum_3m >= 0)
        ):
            wait_reasons.append("1m momentum is not supported by the prior 3m move")
        elif ((bullish_trend_ok or soft_bull_ok) and not bullish_persistent) or (
            (bearish_trend_ok or soft_bear_ok) and not bearish_persistent
        ):
            wait_reasons.append("direction has not persisted across the prior momentum leg")
        else:
            wait_reasons.append("no quick setup currently meets activation standards")

    payload = _wait_payload(
        symbol,
        "Waiting - " + "; ".join(wait_reasons),
        now_utc=now_utc,
        support=support,
        resistance=resistance,
        current_price=spot,
        momentum=momentum_1m,
        momentum_3m=momentum_3m,
        volume_spike=volume_spike,
        breakout=bullish_breakout,
        breakdown=bearish_breakdown,
        oi_confirmed=bool(oi_bullish or oi_bearish),
        confidence=confidence,
        risk_reward_ok_flag=rr_ok,
        risk_reward_reason=rr_reason,
        trap_detected=hard_invalidation,
        rangebound=rangebound,
    )
    return await _finalize_payload(
        symbol,
        payload,
        profile=profile,
        now_utc=now_utc,
        hard_invalidation=hard_invalidation,
    )
