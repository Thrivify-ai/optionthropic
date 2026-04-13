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

from app.analytics.main_signal_runtime import recent_news_impact_score
from app.analytics.market_scanner import fetch_market_breadth_snapshot
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
from app.analytics.quick_signal_cache import cache_quick_signal_payload
from app.analytics.trade_manager import (
    apply_managed_trade_decision,
    stop_threshold_points,
    success_threshold_points,
    serialize_trade_summary,
)
from app.analytics.quick_signal_utils import (
    has_directional_persistence,
    is_quick_rangebound,
)
from app.analytics.quant_signal_context import score_short_covering_risk
from app.analytics.volatility_profile import load_intraday_volatility_profile, scale_threshold, scale_trade_thresholds
from app.config import settings
from app.logging_config import get_logger
from app.models.chain_snapshot import ChainSnapshot
from app.models.underlying_bar import UnderlyingBar
from app.services.runtime_cache import runtime_cache
from app.services.tick_stream import (
    get_latest_tick,
    get_price_seconds_ago,
    get_tick_age_seconds,
)

logger = get_logger(__name__)


_SYMBOL_CONFIG: dict[str, dict[str, float]] = {
    "NIFTY": {
        "bull_mom": 18,
        "bear_mom": -18,
        "mom_3m": 12,
        "fast_10s": 8,
        "fast_20s": 14,
        "fast_60s": 24,
        "soft_ratio": 0.5,
        "pct_min": 0.0006,
        "band_pct": 0.020,
        "target_move": 35,
    },
    "BANKNIFTY": {
        "bull_mom": 45,
        "bear_mom": -45,
        "mom_3m": 30,
        "fast_10s": 18,
        "fast_20s": 32,
        "fast_60s": 55,
        "soft_ratio": 0.5,
        "pct_min": 0.0006,
        "band_pct": 0.020,
        "target_move": 80,
    },
    "SENSEX": {
        "bull_mom": 30,
        "bear_mom": -30,
        "mom_3m": 22,
        "fast_10s": 24,
        "fast_20s": 40,
        "fast_60s": 65,
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
    "fast_10s": 10,
    "fast_20s": 18,
    "fast_60s": 30,
    "soft_ratio": 0.5,
    "pct_min": 0.0006,
    "band_pct": 0.020,
    "target_move": 40,
}

_VOLUME_SPIKE_RATIO = 1.5
_QUICK_SIGNAL_STATE_TTL_SECONDS = 1800
_SNAPSHOT_MAX_AGE_SECONDS = 150
_LIVE_SIGNAL_MAX_AGE_SECONDS = 75


def _cfg(symbol: str) -> dict[str, float]:
    return _SYMBOL_CONFIG.get(symbol.upper(), _DEFAULT_CONFIG)


def _state_key(symbol: str) -> str:
    return f"quick-signal:lifecycle:{symbol.upper()}:v4"


def _timestamp_now(now_utc: datetime | None = None) -> str:
    return (now_utc or datetime.now(timezone.utc)).isoformat()


def _pro_entry_filter_reason(
    *,
    direction: str,
    profile_name: str,
    momentum_1m: float,
    momentum_3m: float | None,
    mom_3m_threshold: float,
    structural_break: bool,
    fast_consensus: bool,
    volume_spike: bool,
    oi_confirmed: bool,
    breadth_ok: bool,
    news_impact_score: int,
) -> str | None:
    """
    Final pro-style entry guard.

    This blocks the classic bad scalps: chasing a one-minute bounce while the
    three-minute structure is still against the trade, or entering on news risk
    before price produces clean follow-through.
    """
    bullish = direction == "bullish"
    same_direction_1m = momentum_1m > 0 if bullish else momentum_1m < 0
    counter_3m = (
        momentum_3m is not None
        and (
            momentum_3m <= -abs(mom_3m_threshold)
            if bullish
            else momentum_3m >= abs(mom_3m_threshold)
        )
    )
    reversal_exception = (
        structural_break
        and same_direction_1m
        and fast_consensus
        and volume_spike
        and (oi_confirmed or breadth_ok)
    )

    if not same_direction_1m:
        side = "bullish" if bullish else "bearish"
        return f"Entry blocked: 1m tape is not {side}; refusing to chase a stale impulse."

    if counter_3m and not reversal_exception:
        return "Entry blocked: 3m structure is still countertrend; waiting for a confirmed reversal instead of a bounce chase."

    if news_impact_score >= 85 and not (
        structural_break
        or (fast_consensus and volume_spike and (oi_confirmed or breadth_ok))
    ):
        return "Entry blocked: news risk is elevated but tradeable price follow-through is not confirmed."

    if profile_name == "closing" and news_impact_score >= 85 and not structural_break and not fast_consensus:
        return "Entry blocked: late-session news tape needs a structural break or fast-tape consensus."

    return None


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
    call_oi_delta: Optional[float] = None,
    put_oi_delta: Optional[float] = None,
    confirmation_count: int = 0,
    required_confirmations: int = 0,
    breadth_score: Optional[int] = None,
    breadth_reason: str | None = None,
    volatility_ratio: float | None = None,
    news_impact_score: int = 0,
    no_trade_regime: str | None = None,
    managed_success_threshold_points: float | None = None,
    managed_stop_points: float | None = None,
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
        "confirmation_count": int(confirmation_count),
        "required_confirmations": int(required_confirmations),
        "risk_reward_ok": bool(risk_reward_ok_flag),
        "risk_reward_reason": risk_reward_reason,
        "trap_detected": bool(trap_detected),
        "rangebound": bool(rangebound),
        "timestamp": _timestamp_now(now_utc),
    }
    if current_price is not None:
        payload["current_price"] = round(current_price, 2)
    if call_oi_delta is not None:
        payload["call_oi_delta"] = round(call_oi_delta, 2)
    if put_oi_delta is not None:
        payload["put_oi_delta"] = round(put_oi_delta, 2)
    if breadth_score is not None:
        payload["breadth_score"] = int(breadth_score)
    if breadth_reason:
        payload["breadth_reason"] = breadth_reason
    if volatility_ratio is not None:
        payload["volatility_ratio"] = round(float(volatility_ratio), 2)
    if news_impact_score:
        payload["news_impact_score"] = int(news_impact_score)
    if no_trade_regime:
        payload["no_trade_regime"] = no_trade_regime
    if managed_success_threshold_points is not None:
        payload["managed_success_threshold_points"] = round(float(managed_success_threshold_points), 2)
    if managed_stop_points is not None:
        payload["managed_stop_points"] = round(float(managed_stop_points), 2)
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
    data_key: str | None = None,
    fast_track: bool = False,
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
        data_key=data_key,
        fast_track=fast_track,
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


async def _apply_trade_management_overlay(
    session: AsyncSession,
    symbol: str,
    payload: dict[str, Any],
    *,
    now_utc: datetime,
) -> dict[str, Any]:
    current_price = payload.get("current_price")
    current_price_value = float(current_price) if current_price is not None else None
    base_signal = str(payload.get("quick_signal") or "Wait")
    hard_exit = payload.get("state") == "cooldown" or payload.get("session") == "closed"
    hard_exit_reason = str(payload.get("state_reason") or payload.get("reason") or "")

    decision, trade_row = await apply_managed_trade_decision(
        session,
        engine="QUICK",
        symbol=symbol,
        base_signal=base_signal,
        confidence=int(payload.get("confidence", 0) or 0),
        current_price=current_price_value,
        reason=str(payload.get("reason") or ""),
        now_utc=now_utc,
        hard_exit=hard_exit,
        hard_exit_reason=hard_exit_reason,
        success_threshold_override=float(payload["managed_success_threshold_points"]) if payload.get("managed_success_threshold_points") is not None else None,
        stop_points_override=float(payload["managed_stop_points"]) if payload.get("managed_stop_points") is not None else None,
        signal_version="quick_v4_live",
    )

    payload["base_quick_signal"] = base_signal
    payload["quick_signal"] = decision.public_signal
    payload["trade_state"] = decision.trade_state
    payload["trade_action"] = decision.action
    payload["entry_price"] = round(float(decision.entry_price), 2) if decision.entry_price is not None else None
    payload["current_points"] = round(float(decision.current_points), 2) if decision.current_points is not None else None
    payload["success_threshold_points"] = round(float(decision.success_threshold_points), 2)
    payload["stop_points"] = round(float(decision.stop_points), 2)
    payload["hold_cycles"] = int(decision.hold_cycles)
    payload["max_favorable_points"] = (
        round(float(decision.max_favorable_points), 2)
        if decision.max_favorable_points is not None
        else None
    )
    payload["max_adverse_points"] = (
        round(float(decision.max_adverse_points), 2)
        if decision.max_adverse_points is not None
        else None
    )
    payload["management_reason"] = decision.management_reason
    payload["trade"] = serialize_trade_summary(trade_row)
    if decision.action in {"hold", "exit"} or (decision.action == "wait" and base_signal in {"Buy CE", "Buy PE"}):
        payload["reason"] = decision.management_reason
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


async def _recent_underlying_bars(
    session: AsyncSession,
    symbol: str,
    limit: int = 4,
) -> list[UnderlyingBar]:
    return (
        await session.execute(
            select(UnderlyingBar)
            .where(
                UnderlyingBar.symbol == symbol,
                UnderlyingBar.timeframe == "1m",
            )
            .order_by(UnderlyingBar.bar_time.desc())
            .limit(limit)
        )
    ).scalars().all()


def _target_move(cfg: dict[str, float]) -> int:
    return int(cfg.get("target_move", 40))


def _dynamic_target_move(
    cfg: dict[str, float],
    volatility_ratio: float | None,
    avg_abs_move_1m: float | None,
) -> int:
    base_target = float(_target_move(cfg))
    if avg_abs_move_1m is None:
        return int(base_target)
    dynamic = max(base_target * 0.85, min(base_target * 1.6, avg_abs_move_1m * 3.4))
    if volatility_ratio is not None and volatility_ratio >= 1.25:
        dynamic *= 1.08
    return int(round(dynamic))


def _breadth_alignment(snapshot: Any, direction: str, *, min_score: int) -> tuple[bool, str]:
    if not getattr(snapshot, "available", False):
        return True, "Breadth scanner unavailable, so no internal leadership block was applied."
    score = int(getattr(snapshot, "breadth_score", 0) or 0)
    if direction == "bullish":
        aligned = score >= min_score and bool(getattr(snapshot, "aligned_bullish", False))
    else:
        aligned = score <= -min_score and bool(getattr(snapshot, "aligned_bearish", False))
    return aligned, str(getattr(snapshot, "reason", "Breadth alignment checked."))


def _tick_momentum(symbol: str, seconds: int, current_price: float | None) -> float | None:
    if current_price is None:
        return None
    price_then = get_price_seconds_ago(symbol, seconds)
    if price_then is None:
        return None
    return round(float(current_price) - float(price_then), 2)


def _adaptive_tick_momentum(
    symbol: str,
    seconds: int,
    current_price: float | None,
    *,
    tolerance_seconds: int,
) -> float | None:
    """Retry momentum lookup with wider tolerance when tick sampling is uneven."""
    if current_price is None:
        return None
    price_then = get_price_seconds_ago(
        symbol,
        seconds,
        tolerance_seconds=max(3, int(tolerance_seconds)),
    )
    if price_then is None:
        return None
    return round(float(current_price) - float(price_then), 2)


def _fast_direction_consensus(direction: str, *momentums: float | None) -> bool:
    if direction == "bullish":
        return sum(1 for value in momentums if value is not None and value > 0) >= 2
    if direction == "bearish":
        return sum(1 for value in momentums if value is not None and value < 0) >= 2
    return False


def _attach_fast_metrics(
    payload: dict[str, Any],
    *,
    momentum_10s: float | None,
    momentum_20s: float | None,
    momentum_60s: float | None,
    data_source: str,
    price_age_seconds: float | None,
    snapshot_age_seconds: float | None,
) -> dict[str, Any]:
    payload["data_source"] = data_source
    payload["momentum_10s"] = momentum_10s
    payload["momentum_20s"] = momentum_20s
    payload["momentum_60s"] = momentum_60s
    payload["price_age_seconds"] = round(float(price_age_seconds), 2) if price_age_seconds is not None else None
    payload["snapshot_age_seconds"] = (
        round(float(snapshot_age_seconds), 2) if snapshot_age_seconds is not None else None
    )
    return payload


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
    call_oi_delta: float,
    put_oi_delta: float,
    confirmation_count: int,
    required_confirmations: int,
    breadth_score: int | None = None,
    breadth_reason: str | None = None,
    volatility_ratio: float | None = None,
    news_impact_score: int = 0,
    managed_success_threshold_points: float | None = None,
    managed_stop_points: float | None = None,
    signal_type: str | None = None,
) -> dict[str, Any]:
    payload = {
        "symbol": symbol,
        "quick_signal": signal,
        "raw_signal": signal,
        "signal_type": signal_type or "standard",
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
        "confirmation_count": int(confirmation_count),
        "required_confirmations": int(required_confirmations),
        "risk_reward_ok": bool(risk_reward_ok_flag),
        "risk_reward_reason": risk_reward_reason,
        "trap_detected": bool(trap_detected),
        "rangebound": bool(rangebound),
        "call_oi_delta": round(call_oi_delta, 2),
        "put_oi_delta": round(put_oi_delta, 2),
        "reason": reason,
        "timestamp": _timestamp_now(now_utc),
    }
    if breadth_score is not None:
        payload["breadth_score"] = int(breadth_score)
    if breadth_reason:
        payload["breadth_reason"] = breadth_reason
    if volatility_ratio is not None:
        payload["volatility_ratio"] = round(float(volatility_ratio), 2)
    if news_impact_score:
        payload["news_impact_score"] = int(news_impact_score)
    if managed_success_threshold_points is not None:
        payload["managed_success_threshold_points"] = round(float(managed_success_threshold_points), 2)
    if managed_stop_points is not None:
        payload["managed_stop_points"] = round(float(managed_stop_points), 2)
    return payload


async def run_quick_signal_engine(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """
    Quick signal engine with session-aware thresholds and lifecycle control.

    Returns a dict with `quick_signal` in {"Buy CE", "Buy PE", "Wait"}.
    """
    symbol = symbol.upper()
    cfg = _cfg(symbol)
    now_utc = datetime.now(timezone.utc)
    profile = session_profile_for(now_utc)

    async def _finish(
        payload: dict[str, Any],
        *,
        hard_invalidation: bool,
        data_key: str | None = None,
        fast_track: bool = False,
    ) -> dict[str, Any]:
        finalized = await _finalize_payload(
            symbol,
            payload,
            profile=profile,
            now_utc=now_utc,
            hard_invalidation=hard_invalidation,
            data_key=data_key,
            fast_track=fast_track,
        )
        finalized = await _apply_trade_management_overlay(
            session,
            symbol,
            finalized,
            now_utc=now_utc,
        )
        await cache_quick_signal_payload(symbol, finalized)
        return finalized

    if profile.name == "closed":
        payload = _wait_payload(
            symbol,
            "Market is closed; quick signals stay paused until the next session.",
            now_utc=now_utc,
        )
        return await _finish(payload, hard_invalidation=False, data_key=f"closed:{symbol}")

    base_bull_mom = adjusted_threshold(cfg["bull_mom"], profile)
    base_bear_mom = -adjusted_threshold(abs(cfg["bear_mom"]), profile)
    base_mom_3m_thresh = adjusted_threshold(cfg["mom_3m"], profile)
    base_fast_10s_thresh = adjusted_threshold(cfg["fast_10s"], profile)
    base_fast_20s_thresh = adjusted_threshold(cfg["fast_20s"], profile)
    base_fast_60s_thresh = adjusted_threshold(cfg["fast_60s"], profile)
    pct_min = cfg["pct_min"] * profile.threshold_multiplier * 100
    soft_ratio = float(cfg.get("soft_ratio", 0.5))

    timestamps = await _latest_timestamps(session, symbol, n=7)
    if len(timestamps) < 2:
        payload = _wait_payload(
            symbol,
            "Insufficient data (need at least 2 snapshots).",
            now_utc=now_utc,
        )
        return await _finish(payload, hard_invalidation=False, data_key=f"stale:{symbol}")

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
        return await _finish(payload, hard_invalidation=False, data_key=f"noprice:{symbol}")

    prev_1m = await _snap(session, symbol, ts_1m)
    if not prev_1m:
        payload = _wait_payload(
            symbol,
            "Cannot read the prior minute snapshot.",
            now_utc=now_utc,
            current_price=curr["price"],
        )
        return await _finish(payload, hard_invalidation=False, data_key=f"noprev:{symbol}")

    snapshot_age_seconds = max(0.0, (now_utc - ts_now).total_seconds())
    latest_tick = get_latest_tick(symbol)
    tick_age_seconds = get_tick_age_seconds(symbol)
    tick_price = None
    tick_timestamp = None
    if latest_tick is not None:
        if latest_tick.get("price") is not None:
            tick_price = float(latest_tick["price"])
        tick_timestamp = latest_tick.get("timestamp")

    tick_fresh = tick_price is not None and tick_age_seconds is not None and tick_age_seconds <= max(
        12,
        settings.fast_tick_poll_seconds * 3,
    )
    spot = tick_price if tick_fresh and tick_price is not None else curr["price"]
    data_source = "tick" if tick_fresh and tick_timestamp else "snapshot"
    signal_data_fresh = bool(tick_fresh or snapshot_age_seconds <= _LIVE_SIGNAL_MAX_AGE_SECONDS)
    data_key = (
        f"{symbol}:{tick_timestamp}:{ts_now.isoformat()}"
        if tick_fresh and tick_timestamp
        else f"{symbol}:{ts_now.isoformat()}"
    )

    if not signal_data_fresh:
        payload = _wait_payload(
            symbol,
            "Quick setup skipped because the latest tape is stale. Waiting for a fresh market update.",
            now_utc=now_utc,
            current_price=spot,
            confidence=0,
            confirmation_count=0,
            required_confirmations=profile.min_confirmation_count,
        )
        payload = _attach_fast_metrics(
            payload,
            momentum_10s=None,
            momentum_20s=None,
            momentum_60s=None,
            data_source=data_source,
            price_age_seconds=tick_age_seconds,
            snapshot_age_seconds=snapshot_age_seconds,
        )
        return await _finish(payload, hard_invalidation=False, data_key=data_key)

    volatility_profile = await load_intraday_volatility_profile(session, symbol)
    volatility_ratio = (
        float(volatility_profile.ratio_to_baseline)
        if volatility_profile is not None
        else 1.0
    )
    bull_mom = scale_threshold(base_bull_mom, volatility_profile, multiplier=1.2)
    bear_mom = -scale_threshold(abs(base_bear_mom), volatility_profile, multiplier=1.2)
    mom_3m_thresh = scale_threshold(base_mom_3m_thresh, volatility_profile, multiplier=1.85)
    fast_10s_thresh = scale_threshold(base_fast_10s_thresh, volatility_profile, multiplier=0.9)
    fast_20s_thresh = scale_threshold(base_fast_20s_thresh, volatility_profile, multiplier=1.25)
    fast_60s_thresh = scale_threshold(base_fast_60s_thresh, volatility_profile, multiplier=2.3)
    target_move = _dynamic_target_move(
        cfg,
        volatility_ratio,
        float(volatility_profile.avg_abs_move_1m) if volatility_profile is not None else None,
    )
    breadth_snapshot = await fetch_market_breadth_snapshot(symbol)
    breadth_score = int(breadth_snapshot.breadth_score or 0)
    news_impact_score = await recent_news_impact_score(session, symbol, now_utc)

    support, resistance = await _support_resistance(
        session,
        symbol,
        ts_now,
        spot,
        cfg["band_pct"],
    )

    bar_rows = await _recent_underlying_bars(session, symbol, limit=4)
    price_10s = _tick_momentum(symbol, 10, spot) if tick_fresh else None
    price_20s = _tick_momentum(symbol, 20, spot) if tick_fresh else None
    price_60s = _tick_momentum(symbol, 60, spot) if tick_fresh else None
    price_180s = _tick_momentum(symbol, 180, spot) if tick_fresh else None
    if tick_fresh and price_60s is None:
        price_60s = _adaptive_tick_momentum(
            symbol,
            60,
            spot,
            tolerance_seconds=max(55, settings.fast_tick_poll_seconds * 18),
        )
    if tick_fresh and price_180s is None:
        price_180s = _adaptive_tick_momentum(
            symbol,
            180,
            spot,
            tolerance_seconds=max(95, settings.fast_tick_poll_seconds * 34),
        )

    momentum_1m = round(spot - prev_1m["price"], 2)
    momentum_3m = None
    momentum_prev_leg = None
    reference_price_1m = prev_1m["price"]

    if price_60s is not None:
        momentum_1m = price_60s
        reference_price_1m = spot - price_60s
        if price_180s is not None:
            momentum_3m = price_180s
            momentum_prev_leg = round(price_180s - price_60s, 2)
        elif ts_3m is not None:
            prev_3m = await _snap(session, symbol, ts_3m)
            if prev_3m and prev_3m["price"]:
                momentum_3m = round(spot - prev_3m["price"], 2)
                momentum_prev_leg = round(reference_price_1m - prev_3m["price"], 2)
    elif len(bar_rows) >= 2:
        latest_bar = bar_rows[0]
        prior_bar = bar_rows[1]
        latest_close = float(latest_bar.close)
        prior_close = float(prior_bar.close)
        momentum_1m = round(latest_close - prior_close, 2)
        reference_price_1m = prior_close
        if len(bar_rows) >= 4:
            third_bar = bar_rows[3]
            momentum_3m = round(latest_close - float(third_bar.close), 2)
            momentum_prev_leg = round(prior_close - float(third_bar.close), 2)
        elif ts_3m is not None:
            prev_3m = await _snap(session, symbol, ts_3m)
            if prev_3m and prev_3m["price"]:
                momentum_3m = round(latest_close - prev_3m["price"], 2)
                momentum_prev_leg = round(prior_close - prev_3m["price"], 2)
    elif ts_3m is not None:
        prev_3m = await _snap(session, symbol, ts_3m)
        if prev_3m and prev_3m["price"]:
            momentum_3m = round(spot - prev_3m["price"], 2)
            momentum_prev_leg = round(prev_1m["price"] - prev_3m["price"], 2)

    pct_1m = (momentum_1m / reference_price_1m * 100) if reference_price_1m else 0.0

    fast_bullish = bool(
        (price_10s is not None and price_10s >= fast_10s_thresh and price_20s is not None and price_20s >= fast_20s_thresh)
        or (price_60s is not None and price_60s >= fast_60s_thresh)
    )
    fast_bearish = bool(
        (price_10s is not None and price_10s <= -fast_10s_thresh and price_20s is not None and price_20s <= -fast_20s_thresh)
        or (price_60s is not None and price_60s <= -fast_60s_thresh)
    )
    fast_bullish_consensus = _fast_direction_consensus("bullish", price_10s, price_20s, price_60s)
    fast_bearish_consensus = _fast_direction_consensus("bearish", price_10s, price_20s, price_60s)

    soft_bull = momentum_1m >= bull_mom * soft_ratio or pct_1m >= pct_min
    soft_bear = momentum_1m <= bear_mom * soft_ratio or pct_1m <= -pct_min
    strong_bullish = fast_bullish or momentum_1m >= bull_mom or (pct_1m >= pct_min and momentum_1m > 0)
    strong_bearish = fast_bearish or momentum_1m <= bear_mom or (pct_1m <= -pct_min and momentum_1m < 0)

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
    breadth_bullish_ok, breadth_bullish_reason = _breadth_alignment(
        breadth_snapshot,
        "bullish",
        min_score=profile.min_breadth_score,
    )
    breadth_bearish_ok, breadth_bearish_reason = _breadth_alignment(
        breadth_snapshot,
        "bearish",
        min_score=profile.min_breadth_score,
    )
    short_covering_risk_bull = score_short_covering_risk(
        signal="Buy CE",
        call_oi_delta=call_oi_delta,
        put_oi_delta=put_oi_delta,
        breakout=bullish_breakout,
        breakdown=False,
        volume_spike=volume_spike,
        writer_support=bool(oi_bullish or breadth_bullish_ok),
    )
    short_covering_risk_bear = score_short_covering_risk(
        signal="Buy PE",
        call_oi_delta=call_oi_delta,
        put_oi_delta=put_oi_delta,
        breakout=False,
        breakdown=bearish_breakdown,
        volume_spike=volume_spike,
        writer_support=bool(oi_bearish or breadth_bearish_ok),
    )
    bullish_confirmation_count = sum(
        1
        for flag in (
            bullish_breakout,
            volume_spike,
            oi_bullish,
            strong_bullish_3m,
            fast_bullish_consensus,
            breadth_bullish_ok,
        )
        if flag
    )
    required_confirmations = int(profile.min_confirmation_count)
    scalp_bullish_impulse = (
        profile.name in {"opening", "closing"}
        and tick_fresh
        and fast_bullish
        and (bullish_breakout or volume_spike)
        and (oi_bullish or breadth_bullish_ok)
    )
    scalp_bearish_impulse = (
        profile.name in {"opening", "closing"}
        and tick_fresh
        and fast_bearish
        and (bearish_breakdown or volume_spike)
        and (oi_bearish or breadth_bearish_ok)
    )
    if scalp_bullish_impulse or scalp_bearish_impulse:
        required_confirmations = max(3, required_confirmations - 1)
    if news_impact_score >= 85 and profile.name == "midday":
        required_confirmations += 1
    bearish_confirmation_count = sum(
        1
        for flag in (
            bearish_breakdown,
            volume_spike,
            oi_bearish,
            strong_bearish_3m,
            fast_bearish_consensus,
            breadth_bearish_ok,
        )
        if flag
    )

    rangebound = is_quick_rangebound(
        spot,
        support,
        resistance,
        momentum_1m,
        momentum_3m,
        bull_mom,
        mom_3m_thresh,
    )
    structure_snapshot_stale = snapshot_age_seconds > _SNAPSHOT_MAX_AGE_SECONDS
    tick_impulse_override = bool(
        tick_fresh
        and structure_snapshot_stale
        and (
            (
                momentum_1m >= bull_mom * 0.85
                and (price_10s is None or price_10s > 0)
                and (price_20s is None or price_20s > 0)
            )
            or (
                momentum_1m <= bear_mom * 0.85
                and (price_10s is None or price_10s < 0)
                and (price_20s is None or price_20s < 0)
            )
        )
    )
    if rangebound and tick_impulse_override:
        rangebound = False
    hard_invalidation = bool(trap_bull or trap_bear or (rangebound and not tick_impulse_override))

    bullish_trend_ok = (
        (strong_bullish and (momentum_3m is None or momentum_3m > 0))
        or (strong_bullish_3m and momentum_1m > 0)
        or (fast_bullish and fast_bullish_consensus)
    )
    bearish_trend_ok = (
        (strong_bearish and (momentum_3m is None or momentum_3m < 0))
        or (strong_bearish_3m and momentum_1m < 0)
        or (fast_bearish and fast_bearish_consensus)
    )

    has_bull_conf = bullish_confirmation_count >= max(2, required_confirmations - 1)
    has_bear_conf = bearish_confirmation_count >= max(2, required_confirmations - 1)
    soft_bull_ok = profile.allow_soft_entries and soft_bull and (momentum_3m is None or momentum_3m > 0) and has_bull_conf
    soft_bear_ok = profile.allow_soft_entries and soft_bear and (momentum_3m is None or momentum_3m < 0) and has_bear_conf

    bullish_persistent = has_directional_persistence(
        momentum_1m,
        momentum_prev_leg,
        "bullish",
    ) or fast_bullish_consensus
    bearish_persistent = has_directional_persistence(
        momentum_1m,
        momentum_prev_leg,
        "bearish",
    ) or fast_bearish_consensus

    midday_compression = (
        profile.name == "midday"
        and rangebound
        and not volume_spike
        and abs(momentum_1m) < max(abs(bull_mom), abs(bear_mom)) * 1.15
    )
    low_volatility_compression = (
        volatility_ratio is not None
        and volatility_ratio < 0.72
        and not volume_spike
        and not bullish_breakout
        and not bearish_breakdown
    )
    stale_snapshot_context = (
        not tick_fresh
        and snapshot_age_seconds > 75
    )
    news_without_followthrough = (
        news_impact_score >= 85
        and not volume_spike
        and not bullish_breakout
        and not bearish_breakdown
        and abs(momentum_1m) < max(abs(bull_mom), abs(bear_mom)) * 1.2
    )
    weak_breadth_divergence = (
        breadth_snapshot.available
        and (
            (strong_bullish and breadth_score <= -profile.min_breadth_score)
            or (strong_bearish and breadth_score >= profile.min_breadth_score)
        )
    )
    regime_block_reason = None
    if midday_compression:
        regime_block_reason = "midday range compression is still dominating"
    elif low_volatility_compression:
        regime_block_reason = "intraday volatility is compressed; waiting for a cleaner expansion regime"
    elif stale_snapshot_context:
        regime_block_reason = "market snapshot is stale and tick stream is not fresh enough for quick execution"
    elif news_without_followthrough:
        regime_block_reason = "news risk is elevated but price has not produced follow-through yet"
    elif weak_breadth_divergence:
        regime_block_reason = "index breadth is diverging from the impulse"

    bullish_entry_blocked = (
        (profile.requires_breakout and not bullish_breakout)
        or short_covering_risk_bull >= 62
        or regime_block_reason is not None
        or not breadth_bullish_ok
    )
    bearish_entry_blocked = (
        (profile.requires_breakout and not bearish_breakdown)
        or short_covering_risk_bear >= 62
        or regime_block_reason is not None
        or not breadth_bearish_ok
    )

    bullish_ready_base = (
        (bullish_trend_ok or soft_bull_ok)
        and bullish_persistent
        and strong_bullish
        and (strong_bullish_3m or fast_bullish)
        and not trap_bull
        and not bullish_entry_blocked
        and bullish_confirmation_count >= required_confirmations
    )
    bearish_ready_base = (
        (bearish_trend_ok or soft_bear_ok)
        and bearish_persistent
        and strong_bearish
        and (strong_bearish_3m or fast_bearish)
        and not trap_bear
        and not bearish_entry_blocked
        and bearish_confirmation_count >= required_confirmations
    )
    extreme_impulse_threshold = max(abs(bull_mom), abs(bear_mom)) * (1.45 if profile.name == "midday" else 1.3)
    impulse_bullish_ready = (
        momentum_1m >= extreme_impulse_threshold
        and tick_fresh
        and (fast_bullish or fast_bullish_consensus)
        and (
            bullish_breakout
            or strong_bullish_3m
            or (momentum_3m is not None and momentum_3m > 0)
            or (
                price_20s is not None
                and price_10s is not None
                and price_20s >= fast_20s_thresh * 1.1
                and price_10s >= fast_10s_thresh * 1.1
            )
        )
        and not trap_bull
        and short_covering_risk_bull < 70
        and (
            breadth_bullish_ok
            or not breadth_snapshot.available
            or (structure_snapshot_stale and momentum_1m >= extreme_impulse_threshold * 1.12)
        )
        and bullish_confirmation_count >= max(2, required_confirmations - 2)
    )
    impulse_bearish_ready = (
        momentum_1m <= -extreme_impulse_threshold
        and tick_fresh
        and (fast_bearish or fast_bearish_consensus)
        and (
            bearish_breakdown
            or strong_bearish_3m
            or (momentum_3m is not None and momentum_3m < 0)
            or (
                price_20s is not None
                and price_10s is not None
                and price_20s <= -fast_20s_thresh * 1.1
                and price_10s <= -fast_10s_thresh * 1.1
            )
        )
        and not trap_bear
        and short_covering_risk_bear < 70
        and (
            breadth_bearish_ok
            or not breadth_snapshot.available
            or (structure_snapshot_stale and momentum_1m <= -extreme_impulse_threshold * 1.12)
        )
        and bearish_confirmation_count >= max(2, required_confirmations - 2)
    )
    bullish_ready = bullish_ready_base or impulse_bullish_ready
    bearish_ready = bearish_ready_base or impulse_bearish_ready
    bullish_signal_type = (
        "impulse_scalp"
        if impulse_bullish_ready and not bullish_ready_base
        else "structure_breakout"
        if bullish_breakout
        else "trend_continuation"
    )
    bearish_signal_type = (
        "impulse_scalp"
        if impulse_bearish_ready and not bearish_ready_base
        else "structure_breakdown"
        if bearish_breakdown
        else "trend_continuation"
    )

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
        confirmation_count=bullish_confirmation_count,
        fresh_data=signal_data_fresh,
        trap=trap_bull,
        rangebound=rangebound,
        risk_reward_ok=bullish_rr_ok,
        breadth_aligned=breadth_bullish_ok,
        breadth_score=breadth_score,
        short_covering_risk=short_covering_risk_bull,
        volatility_ratio=volatility_ratio,
        session_name=profile.name,
        regime_blocked=regime_block_reason is not None and not impulse_bullish_ready,
    )
    if fast_bullish and tick_fresh:
        bullish_confidence = min(100, bullish_confidence + 8)
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
        confirmation_count=bearish_confirmation_count,
        fresh_data=signal_data_fresh,
        trap=trap_bear,
        rangebound=rangebound,
        risk_reward_ok=bearish_rr_ok,
        breadth_aligned=breadth_bearish_ok,
        breadth_score=breadth_score,
        short_covering_risk=short_covering_risk_bear,
        volatility_ratio=volatility_ratio,
        session_name=profile.name,
        regime_blocked=regime_block_reason is not None and not impulse_bearish_ready,
    )
    if fast_bearish and tick_fresh:
        bearish_confidence = min(100, bearish_confidence + 8)

    managed_success_threshold, managed_stop_points = scale_trade_thresholds(
        base_success=success_threshold_points("QUICK", symbol),
        base_stop=stop_threshold_points("QUICK", symbol),
        volatility_ratio=volatility_ratio,
        event_risk=news_impact_score >= 85,
    )

    bullish_live = bullish_ready and bullish_rr_ok and bullish_confidence >= profile.min_confidence
    bearish_live = bearish_ready and bearish_rr_ok and bearish_confidence >= profile.min_confidence
    entry_gate_reason = None
    bullish_entry_gate_reason = None
    bearish_entry_gate_reason = None
    price_dislocation = abs(float(spot) - float(curr["price"]))
    if bullish_live or bearish_live:
        if profile.name == "midday" and max(bullish_confidence, bearish_confidence) < 92:
            entry_gate_reason = "midday tape is still noisy; fresh entries require near-perfect conviction"
        elif volatility_ratio is not None and volatility_ratio < 0.80:
            entry_gate_reason = "intraday volatility is too compressed for a clean quick entry"
        elif (
            volatility_ratio is not None
            and volatility_ratio > 1.75
            and max(bullish_confidence, bearish_confidence) < profile.min_confidence + 5
        ):
            entry_gate_reason = "tape is hyper-volatile; waiting for cleaner continuation before entry"
        elif tick_fresh and price_dislocation > max(6.0, target_move * 0.18):
            entry_gate_reason = "price dislocation is elevated; waiting for tape and snapshot to re-align"
    if entry_gate_reason and not (impulse_bullish_ready or impulse_bearish_ready):
        bullish_live = False
        bearish_live = False

    if bullish_live:
        bullish_entry_gate_reason = _pro_entry_filter_reason(
            direction="bullish",
            profile_name=profile.name,
            momentum_1m=momentum_1m,
            momentum_3m=momentum_3m,
            mom_3m_threshold=mom_3m_thresh,
            structural_break=bullish_breakout,
            fast_consensus=fast_bullish_consensus,
            volume_spike=volume_spike,
            oi_confirmed=oi_bullish,
            breadth_ok=breadth_bullish_ok,
            news_impact_score=news_impact_score,
        )
        if bullish_entry_gate_reason:
            bullish_live = False
            entry_gate_reason = bullish_entry_gate_reason
    if bearish_live:
        bearish_entry_gate_reason = _pro_entry_filter_reason(
            direction="bearish",
            profile_name=profile.name,
            momentum_1m=momentum_1m,
            momentum_3m=momentum_3m,
            mom_3m_threshold=mom_3m_thresh,
            structural_break=bearish_breakdown,
            fast_consensus=fast_bearish_consensus,
            volume_spike=volume_spike,
            oi_confirmed=oi_bearish,
            breadth_ok=breadth_bearish_ok,
            news_impact_score=news_impact_score,
        )
        if bearish_entry_gate_reason:
            bearish_live = False
            entry_gate_reason = bearish_entry_gate_reason

    bullish_fast_track = (
        bullish_live
        and fast_bullish
        and tick_fresh
        and bullish_confirmation_count >= 2
        and breadth_bullish_ok
        and bullish_confidence >= profile.min_confidence + 4
    )
    bearish_fast_track = (
        bearish_live
        and fast_bearish
        and tick_fresh
        and bearish_confirmation_count >= 2
        and breadth_bearish_ok
        and bearish_confidence >= profile.min_confidence + 4
    )

    if bullish_live and not bearish_live:
        ext: list[str] = []
        if bullish_breakout and resistance is not None:
            ext.append(f"breakout above {int(resistance):,}")
        if oi_bullish:
            ext.append("call covering with put support")
        if breadth_bullish_ok and breadth_snapshot.available:
            ext.append(f"breadth {breadth_score:+d}")
        if volume_spike:
            ext.append("volume expansion")
        if fast_bullish and price_10s is not None:
            ext.append(f"fast tape +{price_10s:.0f} in 10s")
        if news_impact_score >= 85:
            ext.append(f"news impact {news_impact_score}")
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
            call_oi_delta=call_oi_delta,
            put_oi_delta=put_oi_delta,
            confirmation_count=bullish_confirmation_count,
            required_confirmations=required_confirmations,
            breadth_score=breadth_score,
            breadth_reason=breadth_bullish_reason,
            volatility_ratio=volatility_ratio,
            news_impact_score=news_impact_score,
            managed_success_threshold_points=managed_success_threshold,
            managed_stop_points=managed_stop_points,
            signal_type=bullish_signal_type,
        )
        payload = _attach_fast_metrics(
            payload,
            momentum_10s=price_10s,
            momentum_20s=price_20s,
            momentum_60s=price_60s,
            data_source=data_source,
            price_age_seconds=tick_age_seconds,
            snapshot_age_seconds=snapshot_age_seconds,
        )
        return await _finish(
            payload,
            hard_invalidation=hard_invalidation,
            data_key=data_key,
            fast_track=bullish_fast_track,
        )

    if bearish_live and not bullish_live:
        ext = []
        if bearish_breakdown and support is not None:
            ext.append(f"breakdown below {int(support):,}")
        if oi_bearish:
            ext.append("put covering with call pressure")
        if breadth_bearish_ok and breadth_snapshot.available:
            ext.append(f"breadth {breadth_score:+d}")
        if volume_spike:
            ext.append("volume expansion")
        if fast_bearish and price_10s is not None:
            ext.append(f"fast tape {price_10s:.0f} in 10s")
        if news_impact_score >= 85:
            ext.append(f"news impact {news_impact_score}")
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
            call_oi_delta=call_oi_delta,
            put_oi_delta=put_oi_delta,
            confirmation_count=bearish_confirmation_count,
            required_confirmations=required_confirmations,
            breadth_score=breadth_score,
            breadth_reason=breadth_bearish_reason,
            volatility_ratio=volatility_ratio,
            news_impact_score=news_impact_score,
            managed_success_threshold_points=managed_success_threshold,
            managed_stop_points=managed_stop_points,
            signal_type=bearish_signal_type,
        )
        payload = _attach_fast_metrics(
            payload,
            momentum_10s=price_10s,
            momentum_20s=price_20s,
            momentum_60s=price_60s,
            data_source=data_source,
            price_age_seconds=tick_age_seconds,
            snapshot_age_seconds=snapshot_age_seconds,
        )
        return await _finish(
            payload,
            hard_invalidation=hard_invalidation,
            data_key=data_key,
            fast_track=bearish_fast_track,
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
            call_oi_delta=call_oi_delta,
            put_oi_delta=put_oi_delta,
            confirmation_count=max(bullish_confirmation_count, bearish_confirmation_count),
            required_confirmations=required_confirmations,
            breadth_score=breadth_score,
            breadth_reason=breadth_snapshot.reason,
            volatility_ratio=volatility_ratio,
            news_impact_score=news_impact_score,
            managed_success_threshold_points=managed_success_threshold,
            managed_stop_points=managed_stop_points,
        )
        payload = _attach_fast_metrics(
            payload,
            momentum_10s=price_10s,
            momentum_20s=price_20s,
            momentum_60s=price_60s,
            data_source=data_source,
            price_age_seconds=tick_age_seconds,
            snapshot_age_seconds=snapshot_age_seconds,
        )
        return await _finish(payload, hard_invalidation=hard_invalidation, data_key=data_key)

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
    elif entry_gate_reason:
        wait_reasons.append(entry_gate_reason)
    elif regime_block_reason:
        wait_reasons.append(regime_block_reason)
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
            if price_10s is not None and price_20s is not None:
                msg += f"; 10s {price_10s:+.0f}; 20s {price_20s:+.0f}"
            wait_reasons.append(f"momentum is below the required session-adjusted threshold ({msg})")
        elif ((bullish_trend_ok or soft_bull_ok) and bullish_confirmation_count < required_confirmations) or (
            (bearish_trend_ok or soft_bear_ok) and bearish_confirmation_count < required_confirmations
        ):
            if bullish_confirmation_count >= bearish_confirmation_count:
                wait_reasons.append(
                    f"bullish tape exists, but only {bullish_confirmation_count}/{required_confirmations} confirmations are present"
                )
            else:
                wait_reasons.append(
                    f"bearish tape exists, but only {bearish_confirmation_count}/{required_confirmations} confirmations are present"
                )
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
        elif breadth_snapshot.available and (
            (strong_bullish and not breadth_bullish_ok)
            or (strong_bearish and not breadth_bearish_ok)
        ):
            wait_reasons.append("internal breadth and leadership are not aligned with the impulse")
        elif short_covering_risk_bull >= 62 or short_covering_risk_bear >= 62:
            wait_reasons.append("OI still looks more like covering than fresh conviction")
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
        call_oi_delta=call_oi_delta,
        put_oi_delta=put_oi_delta,
        confirmation_count=max(bullish_confirmation_count, bearish_confirmation_count),
        required_confirmations=required_confirmations,
        breadth_score=breadth_score,
        breadth_reason=breadth_snapshot.reason,
        volatility_ratio=volatility_ratio,
        news_impact_score=news_impact_score,
        no_trade_regime=entry_gate_reason or regime_block_reason,
        managed_success_threshold_points=managed_success_threshold,
        managed_stop_points=managed_stop_points,
    )
    payload = _attach_fast_metrics(
        payload,
        momentum_10s=price_10s,
        momentum_20s=price_20s,
        momentum_60s=price_60s,
        data_source=data_source,
        price_age_seconds=tick_age_seconds,
        snapshot_age_seconds=snapshot_age_seconds,
    )
    return await _finish(payload, hard_invalidation=hard_invalidation, data_key=data_key)
