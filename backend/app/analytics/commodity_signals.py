"""
Commodity futures signals for MCX contracts.

Two layers:
  - Quick signal: short burst detection with stricter momentum confirmation
  - Long-term signal: 5m/30m/60m structure with setup vs active separation
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.trade_manager import (
    apply_managed_trade_decision,
    serialize_trade_summary,
    stop_threshold_points,
    success_threshold_points,
)
from app.analytics.volatility_profile import scale_trade_thresholds
from app.models.global_news_alert import GlobalNewsAlert
from app.models.commodity_snapshot import CommoditySnapshot
from app.services.runtime_cache import runtime_cache

Signal = Literal["LONG", "SHORT", "WAIT"]
CONF_THRESHOLD = 70


@dataclass
class WindowSeries:
    current: float
    current_volume: float
    prev_1m: Optional[float]
    prev_3m: Optional[float]
    prev_5m: Optional[float]
    prev_30m: Optional[float]
    prev_60m: Optional[float]
    vol_5m_avg: float
    current_ts: Optional[datetime] = None


async def _price_at_or_before(session: AsyncSession, symbol: str, ts: datetime) -> Optional[float]:
    row = (
        await session.execute(
            select(CommoditySnapshot.price)
            .where(CommoditySnapshot.symbol == symbol, CommoditySnapshot.timestamp <= ts)
            .order_by(desc(CommoditySnapshot.timestamp))
            .limit(1)
        )
    ).scalars().first()
    return float(row) if row is not None else None


async def _latest_price(session: AsyncSession, symbol: str) -> tuple[Optional[float], Optional[datetime], float]:
    row = (
        await session.execute(
            select(CommoditySnapshot.price, CommoditySnapshot.timestamp, CommoditySnapshot.volume)
            .where(CommoditySnapshot.symbol == symbol)
            .order_by(desc(CommoditySnapshot.timestamp))
            .limit(1)
        )
    ).one_or_none()
    if not row:
        return None, None, 0.0
    return float(row[0]), row[1], float(row[2] or 0.0)


async def _avg_minute_volume_last_5m(session: AsyncSession, symbol: str, now_ts: datetime) -> float:
    start = now_ts - timedelta(minutes=5)
    value = (
        await session.execute(
            select(func.avg(CommoditySnapshot.volume))
            .where(
                CommoditySnapshot.symbol == symbol,
                CommoditySnapshot.timestamp >= start,
                CommoditySnapshot.timestamp <= now_ts,
            )
        )
    ).scalar()
    return float(value or 0.0)


async def _recent_prices(session: AsyncSession, symbol: str, limit: int = 12) -> list[float]:
    rows = (
        await session.execute(
            select(CommoditySnapshot.price)
            .where(CommoditySnapshot.symbol == symbol)
            .order_by(desc(CommoditySnapshot.timestamp))
            .limit(limit)
        )
    ).scalars().all()
    return [float(row) for row in rows if row is not None]


def _direction_consistency(prices: list[float]) -> tuple[int, float]:
    """
    Returns (direction, consistency_ratio).
      direction: +1 (up), -1 (down), 0 (flat/unknown)
      consistency_ratio: max(up_moves, down_moves) / total_moves
    """
    if len(prices) < 4:
        return 0, 0.0

    ups = downs = 0
    for index in range(len(prices) - 1):
        current = prices[index]
        previous = prices[index + 1]
        if current > previous:
            ups += 1
        elif current < previous:
            downs += 1

    total = ups + downs
    if total == 0:
        return 0, 0.0
    direction = 1 if ups > downs else -1 if downs > ups else 0
    return direction, max(ups, downs) / total


async def get_series(session: AsyncSession, symbol: str) -> Optional[WindowSeries]:
    current, current_ts, current_volume = await _latest_price(session, symbol)
    if current is None or current_ts is None:
        return None

    prev_1m = await _price_at_or_before(session, symbol, current_ts - timedelta(minutes=1))
    prev_3m = await _price_at_or_before(session, symbol, current_ts - timedelta(minutes=3))
    prev_5m = await _price_at_or_before(session, symbol, current_ts - timedelta(minutes=5))
    prev_30m = await _price_at_or_before(session, symbol, current_ts - timedelta(minutes=30))
    prev_60m = await _price_at_or_before(session, symbol, current_ts - timedelta(minutes=60))
    vol_avg = await _avg_minute_volume_last_5m(session, symbol, current_ts)

    return WindowSeries(
        current=current,
        current_volume=current_volume,
        prev_1m=prev_1m,
        prev_3m=prev_3m,
        prev_5m=prev_5m,
        prev_30m=prev_30m,
        prev_60m=prev_60m,
        vol_5m_avg=vol_avg,
        current_ts=current_ts,
    )


def _pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous * 100.0


def _momentum(current: float, previous: Optional[float]) -> Optional[float]:
    if previous is None:
        return None
    return round(current - previous, 2)


def _vol_spike(current_vol: float, avg_vol: float) -> bool:
    return avg_vol > 0 and current_vol >= 1.5 * avg_vol


def _symbol_thresholds(symbol: str) -> dict[str, float]:
    sym = symbol.upper()
    if sym == "CRUDEOIL":
        return {"mom_1m": 10.0, "mom_3m": 20.0, "mom_5m": 28.0}
    if sym == "NATGAS":
        return {"mom_1m": 2.0, "mom_3m": 5.0, "mom_5m": 7.0}
    if sym == "GOLD":
        return {"mom_1m": 35.0, "mom_3m": 70.0, "mom_5m": 95.0}
    if sym == "SILVER":
        return {"mom_1m": 40.0, "mom_3m": 80.0, "mom_5m": 110.0}
    return {"mom_1m": 8.0, "mom_3m": 18.0, "mom_5m": 24.0}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, value)))


def _source_timestamp(series: WindowSeries) -> str | None:
    if series.current_ts is None:
        return None
    return series.current_ts.isoformat()


def _commodity_entry_signal(signal: str | None) -> str:
    normalized = str(signal or "WAIT").upper()
    if normalized in {"LONG", "SHORT"}:
        return normalized
    return "Wait"


def _managed_public_state(trade_state: str, fallback_state: str | None) -> str:
    if trade_state in {"entry", "hold"}:
        return "active"
    if trade_state == "exit":
        return "exit"
    return fallback_state or "idle"


async def _with_managed_commodity_state(
    session: AsyncSession,
    *,
    symbol: str,
    engine: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Add index-like managed lifecycle to commodity signals.

    The outward signal vocabulary remains futures-native:
    LONG / SHORT / HOLD LONG / HOLD SHORT / EXIT LONG / EXIT SHORT / WAIT.
    """
    if session is None:
        return payload

    current_price = payload.get("current_price")
    if current_price is None:
        return payload

    raw_signal = str(payload.get("signal") or "WAIT").upper()
    base_signal = _commodity_entry_signal(raw_signal)
    confidence = int(payload.get("confidence") or 0)
    reason = str(payload.get("reason") or "Commodity setup is not ready.")
    source_key = payload.get("source_timestamp") or payload.get("timestamp")
    data_key = (
        f"{engine}:{symbol.upper()}:{source_key}:{raw_signal}:"
        f"{confidence}:{payload.get('state')}:{payload.get('confirmation_count')}"
    )
    cache_key = f"commodity-managed-signal:{engine}:{symbol.upper()}"
    cached = await runtime_cache.get_json(cache_key)
    if isinstance(cached, dict) and cached.get("data_key") == data_key:
        cached_payload = cached.get("payload")
        if isinstance(cached_payload, dict):
            return cached_payload

    volatility_ratio = float(payload.get("volatility_ratio") or 1.0)
    news_impact = int(payload.get("news_impact_score") or 0)
    success_threshold, stop_points = scale_trade_thresholds(
        base_success=success_threshold_points(engine, symbol),
        base_stop=stop_threshold_points(engine, symbol),
        volatility_ratio=volatility_ratio,
        event_risk=news_impact >= 80,
    )

    decision, trade_row = await apply_managed_trade_decision(
        session,
        engine=engine,
        symbol=symbol,
        base_signal=base_signal,
        confidence=confidence,
        current_price=float(current_price),
        reason=reason,
        now_utc=datetime.now(timezone.utc),
        success_threshold_override=success_threshold,
        stop_points_override=stop_points,
        signal_version=f"{engine.lower()}_v1",
    )

    managed = dict(payload)
    managed["raw_signal"] = raw_signal
    managed["base_signal"] = base_signal
    managed["signal"] = decision.public_signal
    managed["trade_state"] = decision.trade_state
    managed["state"] = _managed_public_state(decision.trade_state, str(payload.get("state") or "idle"))
    managed["entry_ready"] = decision.action == "entry"
    managed["trade_active"] = decision.action in {"entry", "hold"}
    managed["managed_reason"] = decision.management_reason
    if decision.action in {"hold", "exit"} or (decision.action == "wait" and base_signal in {"LONG", "SHORT"}):
        managed["reason"] = decision.management_reason
    managed["entry_price"] = decision.entry_price
    managed["current_price"] = decision.current_price
    managed["current_points"] = decision.current_points
    managed["success_threshold_points"] = decision.success_threshold_points
    managed["stop_points"] = decision.stop_points
    managed["hold_cycles"] = decision.hold_cycles
    managed["max_favorable_points"] = decision.max_favorable_points
    managed["max_adverse_points"] = decision.max_adverse_points
    managed["trade"] = serialize_trade_summary(trade_row)

    await runtime_cache.set_json(
        cache_key,
        {"data_key": data_key, "payload": managed},
        ttl_seconds=45,
    )
    return managed


def _dir(current: float, previous: Optional[float]) -> int:
    if previous is None:
        return 0
    if current > previous:
        return 1
    if current < previous:
        return -1
    return 0


def _volatility_ratio(symbol: str, recent_prices: list[float]) -> float:
    if len(recent_prices) < 6:
        return 1.0
    baseline = {
        "CRUDEOIL": 7.0,
        "NATGAS": 1.6,
        "GOLD": 26.0,
        "SILVER": 30.0,
    }.get(symbol.upper(), 6.0)
    deltas = [abs(recent_prices[i] - recent_prices[i + 1]) for i in range(len(recent_prices) - 1)]
    avg_abs = sum(deltas) / max(1, len(deltas))
    return max(0.8, min(1.7, avg_abs / max(1.0, baseline)))


async def _recent_news_impact_score(session: AsyncSession, symbol: str) -> int:
    if session is None:
        return 0
    symbol_key = symbol.upper()
    best = 0.0
    alerts = (
        await session.execute(
            select(GlobalNewsAlert)
            .where(
                GlobalNewsAlert.is_critical.is_(True),
                GlobalNewsAlert.fetched_at >= datetime.now(timezone.utc) - timedelta(hours=8),
            )
            .order_by(desc(GlobalNewsAlert.impact_score), desc(GlobalNewsAlert.fetched_at))
            .limit(20)
        )
    ).scalars().all()
    now_utc = datetime.now(timezone.utc)
    for row in alerts:
        affected = {str(item).upper() for item in (row.affected_symbols or [])}
        if symbol_key in affected:
            raw_score = float(row.impact_score or 0)
            fetched_at = row.fetched_at
            if fetched_at is None:
                continue
            fetched = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
            age_minutes = max(0.0, (now_utc - fetched).total_seconds() / 60.0)
            decay = math.exp(-age_minutes / 150.0)
            decayed = raw_score * decay
            if age_minutes <= 40:
                decayed = max(decayed, raw_score * 0.9)
            best = max(best, decayed)
    return int(max(0, min(100, round(best))))


async def commodity_quick_signal(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """
    Quick signal: detect short commodity burst moves, but only when 1m/3m/5m
    momentum and recent tape direction agree. This keeps the engine sparse.
    """
    series = await get_series(session, symbol)
    if not series:
        return {
            "symbol": symbol,
            "signal": "WAIT",
            "reason": "No data yet",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    thresholds = _symbol_thresholds(symbol)
    recent = await _recent_prices(session, symbol, limit=10)
    vol_ratio = _volatility_ratio(symbol, recent)
    news_impact = await _recent_news_impact_score(session, symbol)
    thresholds = {
        key: round(max(value * 0.85, min(value * 1.7, value * vol_ratio)), 2)
        for key, value in thresholds.items()
    }
    mom1 = _momentum(series.current, series.prev_1m)
    mom3 = _momentum(series.current, series.prev_3m)
    mom5 = _momentum(series.current, series.prev_5m)

    strong_long_1m = mom1 is not None and mom1 >= thresholds["mom_1m"]
    strong_long_3m = mom3 is not None and mom3 >= thresholds["mom_3m"]
    strong_long_5m = mom5 is not None and mom5 >= thresholds["mom_5m"]
    strong_short_1m = mom1 is not None and mom1 <= -thresholds["mom_1m"]
    strong_short_3m = mom3 is not None and mom3 <= -thresholds["mom_3m"]
    strong_short_5m = mom5 is not None and mom5 <= -thresholds["mom_5m"]

    direction, consistency = _direction_consistency(recent)
    vol_spike = _vol_spike(series.current_volume, series.vol_5m_avg)
    consistent_long = direction == 1 and consistency >= 0.65
    consistent_short = direction == -1 and consistency >= 0.65
    news_without_followthrough = news_impact >= 80 and not vol_spike and consistency < 0.72

    bullish_confirmation_count = sum(
        (
            strong_long_1m,
            strong_long_3m,
            strong_long_5m,
            consistent_long,
            vol_spike,
            not news_without_followthrough,
        )
    )
    bearish_confirmation_count = sum(
        (
            strong_short_1m,
            strong_short_3m,
            strong_short_5m,
            consistent_short,
            vol_spike,
            not news_without_followthrough,
        )
    )
    required_confirmations = 5 if news_impact >= 80 else 4

    long_ready = (
        strong_long_1m
        and strong_long_3m
        and strong_long_5m
        and consistent_long
        and vol_spike
        and not news_without_followthrough
        and bullish_confirmation_count >= required_confirmations
    )
    short_ready = (
        strong_short_1m
        and strong_short_3m
        and strong_short_5m
        and consistent_short
        and vol_spike
        and not news_without_followthrough
        and bearish_confirmation_count >= required_confirmations
    )
    long_setup = (
        strong_long_1m
        and strong_long_3m
        and consistent_long
        and bullish_confirmation_count >= required_confirmations - 1
    )
    short_setup = (
        strong_short_1m
        and strong_short_3m
        and consistent_short
        and bearish_confirmation_count >= required_confirmations - 1
    )

    momentum_score = 0.0
    if mom1 is not None:
        momentum_score += min(24.0, abs(mom1) / max(1e-9, thresholds["mom_1m"]) * 12.0)
    if mom3 is not None:
        momentum_score += min(28.0, abs(mom3) / max(1e-9, thresholds["mom_3m"]) * 14.0)
    if mom5 is not None:
        momentum_score += min(22.0, abs(mom5) / max(1e-9, thresholds["mom_5m"]) * 11.0)
    confidence = _clamp(
        momentum_score
        + consistency * 18.0
        + (8.0 if vol_spike else 0.0)
        + max(bullish_confirmation_count, bearish_confirmation_count) * 5.0
        + (6.0 if news_impact >= 80 and not news_without_followthrough else 0.0)
    )

    if long_ready:
        payload = {
            "symbol": symbol,
            "signal": "LONG",
            "state": "active",
            "entry_ready": True,
            "setup_direction": "LONG",
            "confidence": max(confidence, 78),
            "momentum_1m": mom1,
            "momentum_3m": mom3,
            "momentum_5m": mom5,
            "confirmation_count": bullish_confirmation_count,
            "required_confirmations": required_confirmations,
            "direction_consistency": round(consistency, 2),
            "volume_spike": vol_spike,
            "volatility_ratio": round(vol_ratio, 2),
            "news_impact_score": news_impact,
            "current_price": series.current,
            "source_timestamp": _source_timestamp(series),
            "reason": (
                f"+{mom1:.0f} (1m), +{mom3:.0f} (3m), +{mom5:.0f} (5m) with "
                f"{bullish_confirmation_count}/{required_confirmations} confirmations - clean momentum burst"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await _with_managed_commodity_state(session, symbol=symbol, engine="COMMODITY_QUICK", payload=payload)
    if short_ready:
        payload = {
            "symbol": symbol,
            "signal": "SHORT",
            "state": "active",
            "entry_ready": True,
            "setup_direction": "SHORT",
            "confidence": max(confidence, 78),
            "momentum_1m": mom1,
            "momentum_3m": mom3,
            "momentum_5m": mom5,
            "confirmation_count": bearish_confirmation_count,
            "required_confirmations": required_confirmations,
            "direction_consistency": round(consistency, 2),
            "volume_spike": vol_spike,
            "volatility_ratio": round(vol_ratio, 2),
            "news_impact_score": news_impact,
            "current_price": series.current,
            "source_timestamp": _source_timestamp(series),
            "reason": (
                f"{mom1:.0f} (1m), {mom3:.0f} (3m), {mom5:.0f} (5m) with "
                f"{bearish_confirmation_count}/{required_confirmations} confirmations - clean downside burst"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await _with_managed_commodity_state(session, symbol=symbol, engine="COMMODITY_QUICK", payload=payload)

    setup_direction = "LONG" if long_setup else "SHORT" if short_setup else None
    setup_confirmations = (
        bullish_confirmation_count
        if long_setup
        else bearish_confirmation_count
        if short_setup
        else max(bullish_confirmation_count, bearish_confirmation_count)
    )
    payload = {
        "symbol": symbol,
        "signal": "WAIT",
        "state": "setup" if setup_direction else "idle",
        "entry_ready": False,
        "setup_direction": setup_direction,
        "confidence": min(confidence, CONF_THRESHOLD - 1),
        "momentum_1m": mom1,
        "momentum_3m": mom3,
        "momentum_5m": mom5,
        "confirmation_count": setup_confirmations,
        "required_confirmations": required_confirmations,
        "direction_consistency": round(consistency, 2),
        "volume_spike": vol_spike,
        "volatility_ratio": round(vol_ratio, 2),
        "news_impact_score": news_impact,
        "current_price": series.current,
        "source_timestamp": _source_timestamp(series),
        "reason": (
            f"WAIT: setup {setup_direction or 'not ready'} with {setup_confirmations}/{required_confirmations} confirmations. "
            f"Momentum {(mom1 or 0):.0f} (1m), {(mom3 or 0):.0f} (3m), {(mom5 or 0):.0f} (5m)."
            + (" High-impact news is present, but price has not confirmed it cleanly yet." if news_without_followthrough else "")
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return await _with_managed_commodity_state(session, symbol=symbol, engine="COMMODITY_QUICK", payload=payload)


async def commodity_long_term_signal(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """
    Long-term signal: sustained trend with 5m/30m/60m structure.
    Returns WAIT with setup metadata until the shorter leg joins the broader bias.
    """
    series = await get_series(session, symbol)
    if not series:
        return {
            "symbol": symbol,
            "signal": "WAIT",
            "reason": "No data yet",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    recent = await _recent_prices(session, symbol, limit=20)
    vol_ratio = _volatility_ratio(symbol, recent[:10])
    news_impact = await _recent_news_impact_score(session, symbol)

    d5 = _dir(series.current, series.prev_5m)
    d30 = _dir(series.current, series.prev_30m)
    d60 = _dir(series.current, series.prev_60m)

    pct5 = _pct(series.current, series.prev_5m)
    pct30 = _pct(series.current, series.prev_30m)
    pct60 = _pct(series.current, series.prev_60m)

    mag_5_ok = pct5 is not None and abs(pct5) >= 0.10
    mag_30_ok = pct30 is not None and abs(pct30) >= 0.20
    mag_60_ok = pct60 is not None and abs(pct60) >= 0.30

    direction, consistency = _direction_consistency(recent)
    consistent_long = direction == 1 and consistency >= 0.68
    consistent_short = direction == -1 and consistency >= 0.68

    all_up = d5 > 0 and d30 > 0 and d60 > 0
    all_down = d5 < 0 and d30 < 0 and d60 < 0
    event_guard = news_impact >= 80 and vol_ratio < 0.9
    long_ready = all_up and mag_5_ok and mag_30_ok and mag_60_ok and consistent_long and not event_guard
    short_ready = all_down and mag_5_ok and mag_30_ok and mag_60_ok and consistent_short and not event_guard
    long_setup = d30 > 0 and d60 > 0 and mag_30_ok and mag_60_ok
    short_setup = d30 < 0 and d60 < 0 and mag_30_ok and mag_60_ok

    long_confirmation_count = sum((d5 > 0, d30 > 0, d60 > 0, mag_5_ok, mag_30_ok, mag_60_ok, consistent_long))
    short_confirmation_count = sum((d5 < 0, d30 < 0, d60 < 0, mag_5_ok, mag_30_ok, mag_60_ok, consistent_short))
    required_confirmations = 6

    long_confidence = _clamp(
        32
        + (8 if d5 > 0 else 0)
        + (12 if d30 > 0 else 0)
        + (14 if d60 > 0 else 0)
        + (8 if mag_5_ok else 0)
        + (10 if mag_30_ok else 0)
        + (10 if mag_60_ok else 0)
        + int(consistency * 12)
        + (6 if news_impact >= 80 and not event_guard else 0)
    )
    short_confidence = _clamp(
        32
        + (8 if d5 < 0 else 0)
        + (12 if d30 < 0 else 0)
        + (14 if d60 < 0 else 0)
        + (8 if mag_5_ok else 0)
        + (10 if mag_30_ok else 0)
        + (10 if mag_60_ok else 0)
        + int(consistency * 12)
        + (6 if news_impact >= 80 and not event_guard else 0)
    )

    if long_ready:
        payload = {
            "symbol": symbol,
            "signal": "LONG",
            "state": "active",
            "entry_ready": True,
            "setup_direction": "LONG",
            "confidence": max(long_confidence, 80),
            "confirmation_count": long_confirmation_count,
            "required_confirmations": required_confirmations,
            "bias_5m": "UP",
            "bias_30m": "UP",
            "bias_60m": "UP",
            "pct_5m": round(pct5 or 0, 2),
            "pct_30m": round(pct30 or 0, 2),
            "pct_60m": round(pct60 or 0, 2),
            "volatility_ratio": round(vol_ratio, 2),
            "news_impact_score": news_impact,
            "current_price": series.current,
            "source_timestamp": _source_timestamp(series),
            "reason": (
                f"Stable uptrend with {long_confirmation_count}/{required_confirmations} confirmations: "
                f"{pct5 or 0:+.2f}% (5m), {pct30 or 0:+.2f}% (30m), {pct60 or 0:+.2f}% (60m)"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await _with_managed_commodity_state(session, symbol=symbol, engine="COMMODITY_LONG", payload=payload)
    if short_ready:
        payload = {
            "symbol": symbol,
            "signal": "SHORT",
            "state": "active",
            "entry_ready": True,
            "setup_direction": "SHORT",
            "confidence": max(short_confidence, 80),
            "confirmation_count": short_confirmation_count,
            "required_confirmations": required_confirmations,
            "bias_5m": "DOWN",
            "bias_30m": "DOWN",
            "bias_60m": "DOWN",
            "pct_5m": round(pct5 or 0, 2),
            "pct_30m": round(pct30 or 0, 2),
            "pct_60m": round(pct60 or 0, 2),
            "volatility_ratio": round(vol_ratio, 2),
            "news_impact_score": news_impact,
            "current_price": series.current,
            "source_timestamp": _source_timestamp(series),
            "reason": (
                f"Stable downtrend with {short_confirmation_count}/{required_confirmations} confirmations: "
                f"{pct5 or 0:+.2f}% (5m), {pct30 or 0:+.2f}% (30m), {pct60 or 0:+.2f}% (60m)"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await _with_managed_commodity_state(session, symbol=symbol, engine="COMMODITY_LONG", payload=payload)

    setup_direction = "LONG" if long_setup else "SHORT" if short_setup else None
    setup_confidence = long_confidence if long_setup else short_confidence if short_setup else 48
    setup_count = (
        long_confirmation_count
        if long_setup
        else short_confirmation_count
        if short_setup
        else max(long_confirmation_count, short_confirmation_count)
    )
    payload = {
        "symbol": symbol,
        "signal": "WAIT",
        "state": "setup" if setup_direction else "idle",
        "entry_ready": False,
        "setup_direction": setup_direction,
        "confirmation_count": setup_count,
        "required_confirmations": required_confirmations,
        "confidence": min(max(setup_confidence, 45), 74),
        "bias_5m": "UP" if d5 > 0 else "DOWN" if d5 < 0 else "FLAT",
        "bias_30m": "UP" if d30 > 0 else "DOWN" if d30 < 0 else "FLAT",
        "bias_60m": "UP" if d60 > 0 else "DOWN" if d60 < 0 else "FLAT",
        "pct_5m": round(pct5 or 0, 2),
        "pct_30m": round(pct30 or 0, 2),
        "pct_60m": round(pct60 or 0, 2),
        "volatility_ratio": round(vol_ratio, 2),
        "news_impact_score": news_impact,
        "current_price": series.current,
        "source_timestamp": _source_timestamp(series),
        "reason": (
            "WAIT: need 5m/30m/60m alignment, 0.10%/0.20%/0.30% magnitude, and persistent direction "
            "before promoting a commodity trend."
            + (" High-impact news is present, so the trend needs stronger follow-through." if event_guard else "")
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return await _with_managed_commodity_state(session, symbol=symbol, engine="COMMODITY_LONG", payload=payload)
