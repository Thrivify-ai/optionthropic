"""
Commodity signals — futures-only (price/volume/oi) signals for MCX.

Two layers:
  - Quick signal (1–3 minute momentum burst)
  - Long-term signal (5m/30m/60m alignment from stored snapshots)

Signal labels are commodity-style:
  LONG / SHORT / WAIT
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commodity_snapshot import CommoditySnapshot

Signal = Literal["LONG", "SHORT", "WAIT"]
CONF_THRESHOLD = 70


@dataclass
class WindowSeries:
    current: float
    prev_1m: Optional[float]
    prev_3m: Optional[float]
    prev_5m: Optional[float]
    prev_30m: Optional[float]
    prev_60m: Optional[float]
    vol_5m_avg: float


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


async def _latest_price(session: AsyncSession, symbol: str) -> tuple[Optional[float], Optional[datetime]]:
    row = (
        await session.execute(
            select(CommoditySnapshot.price, CommoditySnapshot.timestamp)
            .where(CommoditySnapshot.symbol == symbol)
            .order_by(desc(CommoditySnapshot.timestamp))
            .limit(1)
        )
    ).one_or_none()
    if not row:
        return None, None
    return float(row[0]), row[1]


async def _avg_minute_volume_last_5m(session: AsyncSession, symbol: str, now_ts: datetime) -> float:
    start = now_ts - timedelta(minutes=5)
    # avg of stored volume column; if it's zero we still return 0.
    v = (
        await session.execute(
            select(func.avg(CommoditySnapshot.volume))
            .where(
                CommoditySnapshot.symbol == symbol,
                CommoditySnapshot.timestamp >= start,
                CommoditySnapshot.timestamp <= now_ts,
            )
        )
    ).scalar()
    return float(v or 0)


async def _recent_prices(session: AsyncSession, symbol: str, limit: int = 12) -> list[float]:
    rows = (
        await session.execute(
            select(CommoditySnapshot.price)
            .where(CommoditySnapshot.symbol == symbol)
            .order_by(desc(CommoditySnapshot.timestamp))
            .limit(limit)
        )
    ).scalars().all()
    return [float(r) for r in rows if r is not None]


def _direction_consistency(prices: list[float]) -> tuple[int, float]:
    """
    Returns (direction, consistency_ratio).
      direction: +1 (up), -1 (down), 0 (flat/unknown)
      consistency_ratio: max(up_moves, down_moves) / total_moves
    """
    if len(prices) < 4:
        return 0, 0.0
    ups = downs = 0
    for i in range(len(prices) - 1):
        a = prices[i]
        b = prices[i + 1]
        if a > b:
            ups += 1
        elif a < b:
            downs += 1
    total = ups + downs
    if total == 0:
        return 0, 0.0
    direction = 1 if ups > downs else -1 if downs > ups else 0
    return direction, max(ups, downs) / total


async def get_series(session: AsyncSession, symbol: str) -> Optional[WindowSeries]:
    cur, cur_ts = await _latest_price(session, symbol)
    if cur is None or cur_ts is None:
        return None

    prev_1m = await _price_at_or_before(session, symbol, cur_ts - timedelta(minutes=1))
    prev_3m = await _price_at_or_before(session, symbol, cur_ts - timedelta(minutes=3))
    prev_5m = await _price_at_or_before(session, symbol, cur_ts - timedelta(minutes=5))
    prev_30m = await _price_at_or_before(session, symbol, cur_ts - timedelta(minutes=30))
    prev_60m = await _price_at_or_before(session, symbol, cur_ts - timedelta(minutes=60))
    vol_avg = await _avg_minute_volume_last_5m(session, symbol, cur_ts)

    return WindowSeries(
        current=cur,
        prev_1m=prev_1m,
        prev_3m=prev_3m,
        prev_5m=prev_5m,
        prev_30m=prev_30m,
        prev_60m=prev_60m,
        vol_5m_avg=vol_avg,
    )


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100.0


def _momentum(a: float, b: Optional[float]) -> Optional[float]:
    if b is None:
        return None
    return round(a - b, 2)


def _vol_spike(current_vol: float, avg_vol: float) -> bool:
    return avg_vol > 0 and current_vol >= 1.5 * avg_vol


def _symbol_thresholds(symbol: str) -> dict[str, float]:
    """30–40 pt equivalent moves per commodity (scaled by typical price level)."""
    sym = symbol.upper()
    if sym == "CRUDEOIL":
        return {"mom_1m": 10, "mom_3m": 20}   # ~6k level
    if sym == "NATGAS":
        return {"mom_1m": 2.0, "mom_3m": 5.0}
    if sym == "GOLD":
        return {"mom_1m": 35, "mom_3m": 70}  # ~62k level
    if sym == "SILVER":
        return {"mom_1m": 40, "mom_3m": 80}  # ~82k level
    return {"mom_1m": 8, "mom_3m": 18}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, v)))


async def commodity_quick_signal(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """
    Quick signal: detect 30–40 pt equivalent burst moves (1m + 3m momentum).
    Momentum-first: if threshold exceeded in both timeframes, fire.
    """
    s = await get_series(session, symbol)
    if not s:
        return {"symbol": symbol, "signal": "WAIT", "reason": "No data yet", "timestamp": datetime.now(timezone.utc).isoformat()}

    th = _symbol_thresholds(symbol)
    mom1 = _momentum(s.current, s.prev_1m)
    mom3 = _momentum(s.current, s.prev_3m)

    long_ok = mom1 is not None and mom3 is not None and mom1 >= th["mom_1m"] and mom3 >= th["mom_3m"]
    short_ok = mom1 is not None and mom3 is not None and mom1 <= -th["mom_1m"] and mom3 <= -th["mom_3m"]

    recent = await _recent_prices(session, symbol, limit=10)
    d_dir, d_cons = _direction_consistency(recent)
    current_vol = 0.0
    vol_spike = _vol_spike(current_vol, s.vol_5m_avg)

    # Confidence: momentum strength + direction consistency (for display only)
    mom_score = 0.0
    if mom1 is not None:
        mom_score += min(30.0, abs(mom1) / max(1e-9, th["mom_1m"]) * 15.0)
    if mom3 is not None:
        mom_score += min(30.0, abs(mom3) / max(1e-9, th["mom_3m"]) * 15.0)
    conf = _clamp(mom_score + d_cons * 30.0 + (10.0 if vol_spike else 0.0))

    # Momentum-first: fire when 1m + 3m exceed threshold in same direction
    if long_ok:
        return {
            "symbol": symbol,
            "signal": "LONG",
            "confidence": max(conf, 70),
            "momentum_1m": mom1,
            "momentum_3m": mom3,
            "volume_spike": vol_spike,
            "reason": f"+{mom1:.0f} (1m), +{mom3:.0f} (3m) — 30–40 pt equiv burst · expect follow-through",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    if short_ok:
        return {
            "symbol": symbol,
            "signal": "SHORT",
            "confidence": max(conf, 70),
            "momentum_1m": mom1,
            "momentum_3m": mom3,
            "volume_spike": vol_spike,
            "reason": f"{mom1:.0f} (1m), {mom3:.0f} (3m) — 30–40 pt equiv burst · expect follow-through",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    conf_wait = min(conf, CONF_THRESHOLD - 1)
    return {
        "symbol": symbol,
        "signal": "WAIT",
        "confidence": conf_wait,
        "momentum_1m": mom1,
        "momentum_3m": mom3,
        "volume_spike": vol_spike,
        "reason": f"WAIT: momentum {(mom1 or 0):.0f} (1m), {(mom3 or 0):.0f} (3m) below ±{th['mom_1m']}/±{th['mom_3m']} threshold",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _dir(cur: float, prev: Optional[float]) -> int:
    if prev is None:
        return 0
    if cur > prev:
        return 1
    if cur < prev:
        return -1
    return 0


async def commodity_long_term_signal(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """
    Long-term: stable time move. All three timeframes (5m, 30m, 60m) must agree
    in the same direction with meaningful magnitude. For sustained trends.
    """
    s = await get_series(session, symbol)
    if not s:
        return {"symbol": symbol, "signal": "WAIT", "reason": "No data yet", "timestamp": datetime.now(timezone.utc).isoformat()}

    d5  = _dir(s.current, s.prev_5m)
    d30 = _dir(s.current, s.prev_30m)
    d60 = _dir(s.current, s.prev_60m)

    pct30 = _pct(s.current, s.prev_30m)
    pct60 = _pct(s.current, s.prev_60m)

    mag_30_ok = pct30 is not None and abs(pct30) >= 0.20
    mag_60_ok = pct60 is not None and abs(pct60) >= 0.30
    mag_ok = mag_30_ok and mag_60_ok

    recent = await _recent_prices(session, symbol, limit=20)
    d_dir, d_cons = _direction_consistency(recent)

    all_up = d5 > 0 and d30 > 0 and d60 > 0
    all_down = d5 < 0 and d30 < 0 and d60 < 0
    stable_long = all_up and mag_ok and (d_dir == 1 or d_cons >= 0.60)
    stable_short = all_down and mag_ok and (d_dir == -1 or d_cons >= 0.60)

    if stable_long:
        return {
            "symbol": symbol,
            "signal": "LONG",
            "confidence": 75,
            "bias_5m": "UP",
            "bias_30m": "UP",
            "bias_60m": "UP",
            "pct_30m": round(pct30 or 0, 2),
            "pct_60m": round(pct60 or 0, 2),
            "reason": f"Stable uptrend: 5m/30m/60m aligned · {pct30 or 0:+.2f}% (30m), {pct60 or 0:+.2f}% (60m)",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    if stable_short:
        return {
            "symbol": symbol,
            "signal": "SHORT",
            "confidence": 75,
            "bias_5m": "DOWN",
            "bias_30m": "DOWN",
            "bias_60m": "DOWN",
            "pct_30m": round(pct30 or 0, 2),
            "pct_60m": round(pct60 or 0, 2),
            "reason": f"Stable downtrend: 5m/30m/60m aligned · {pct30 or 0:+.2f}% (30m), {pct60 or 0:+.2f}% (60m)",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    conf_wait = 50
    return {
        "symbol": symbol,
        "signal": "WAIT",
        "confidence": conf_wait,
        "bias_5m": "UP" if d5 > 0 else "DOWN" if d5 < 0 else "FLAT",
        "bias_30m": "UP" if d30 > 0 else "DOWN" if d30 < 0 else "FLAT",
        "bias_60m": "UP" if d60 > 0 else "DOWN" if d60 < 0 else "FLAT",
        "pct_30m": round(pct30 or 0, 2),
        "pct_60m": round(pct60 or 0, 2),
        "reason": "WAIT: need 5m/30m/60m aligned + 0.2%/0.3% magnitude for stable move",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

