"""
Quick options buy signal — 10-minute OI buildup detector.

Looks at the last 10 minutes of options chain data and identifies:
  - Put Writing  (put OI building below spot)     → Bullish
  - Call Writing (call OI building above spot)    → Bearish
  - Call Unwinding (call OI collapsing above spot) → Bullish
  - Put Unwinding  (put OI collapsing below spot)  → Bearish

Designed to catch fast institutional moves (accumulation, writing, covering)
that may not yet show up in the slower multi-timeframe signal.

A `news_boost` flag is reserved for future news-signal integration: when a
relevant headline arrives, it will be OR-ed with this OI signal to raise
confidence of sudden directional moves.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models.chain_snapshot import ChainSnapshot

logger = get_logger(__name__)

WINDOW_MINUTES = 10


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _no_signal(symbol: str, reason: str) -> dict[str, Any]:
    return {
        "symbol":         symbol,
        "quick_signal":   "Wait",
        "buildup_type":   None,
        "key_strike":     None,
        "key_oi_change":  None,
        "strength":       None,
        "bull_score":     0,
        "bear_score":     0,
        "reason":         reason,
        "top_signals":    [],
        "window_minutes": WINDOW_MINUTES,
        "news_boost":     False,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }


# ─── Main function ────────────────────────────────────────────────────────────

async def get_quick_signal(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """
    Analyse the last 10 minutes of OI changes and return a directional
    quick signal together with the dominant buildup type and key strike.
    """
    now              = datetime.now(timezone.utc)
    prev_ts_cutoff   = now - timedelta(minutes=WINDOW_MINUTES)

    # ── Latest timestamp ──────────────────────────────────────────────────────
    latest_ts = (
        await session.execute(
            select(func.max(ChainSnapshot.timestamp))
            .where(ChainSnapshot.symbol == symbol)
        )
    ).scalar()
    if not latest_ts:
        return _no_signal(symbol, "No data available")

    # ── Nearest snapshot to 10 minutes ago ───────────────────────────────────
    prev_ts = (
        await session.execute(
            select(func.max(ChainSnapshot.timestamp))
            .where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp <= prev_ts_cutoff,
            )
        )
    ).scalar()

    if not prev_ts or prev_ts == latest_ts:
        return _no_signal(symbol, "Insufficient history (< 10 min of data)")

    # ── Fetch rows at both timestamps ─────────────────────────────────────────
    latest_rows = (
        await session.execute(
            select(ChainSnapshot)
            .where(ChainSnapshot.symbol == symbol,
                   ChainSnapshot.timestamp == latest_ts)
        )
    ).scalars().all()

    prev_rows = (
        await session.execute(
            select(ChainSnapshot)
            .where(ChainSnapshot.symbol == symbol,
                   ChainSnapshot.timestamp == prev_ts)
        )
    ).scalars().all()

    if not latest_rows or not prev_rows:
        return _no_signal(symbol, "Snapshot rows missing")

    spot = float(latest_rows[0].underlying_price or 0)
    if not spot:
        return _no_signal(symbol, "No underlying price")

    # ── OI delta per strike ───────────────────────────────────────────────────
    prev_map = {float(r.strike): r for r in prev_rows}

    deltas: list[dict] = []
    for row in latest_rows:
        strike = float(row.strike)
        prev   = prev_map.get(strike)
        if not prev:
            continue

        call_chg = float(row.call_oi or 0) - float(prev.call_oi or 0)
        put_chg  = float(row.put_oi  or 0) - float(prev.put_oi  or 0)

        deltas.append({
            "strike":    strike,
            "call_chg":  call_chg,
            "put_chg":   put_chg,
            "call_vol":  float(row.call_volume or 0),
            "put_vol":   float(row.put_volume  or 0),
            "above":     strike > spot,
            "below":     strike < spot,
        })

    if not deltas:
        return _no_signal(symbol, "No matching strikes between snapshots")

    # ── Totals for normalisation ──────────────────────────────────────────────
    total_call_build = sum(d["call_chg"] for d in deltas if d["call_chg"] > 0)
    total_put_build  = sum(d["put_chg"]  for d in deltas if d["put_chg"]  > 0)
    total_call_unwind = sum(abs(d["call_chg"]) for d in deltas if d["call_chg"] < 0)
    total_put_unwind  = sum(abs(d["put_chg"])  for d in deltas if d["put_chg"]  < 0)

    # ── Dominant patterns ─────────────────────────────────────────────────────
    # Pattern score: +ve = bullish, -ve = bearish
    bull_score = 0
    bear_score = 0
    top_signals: list[str] = []
    key_strike      = None
    key_oi_change   = None
    buildup_type    = None

    def _strike_fmt(s: float) -> str:
        return f"{int(s):,}"

    def _oi_fmt(v: float) -> str:
        return f"{int(v / 1000)}K" if abs(v) >= 1000 else str(int(v))

    # 1. Put writing at or below spot (bullish): low vol relative to OI build
    put_builds_below = sorted(
        [d for d in deltas if d["below"] and d["put_chg"] > 0],
        key=lambda d: d["put_chg"], reverse=True,
    )
    if put_builds_below:
        top = put_builds_below[0]
        share = top["put_chg"] / total_put_build if total_put_build > 0 else 0
        if share > 0.25:
            # Low vol-to-OI ratio → writing (not buying)
            vol_ratio = top["put_vol"] / (top["put_chg"] + 1)
            if vol_ratio < 1.5:
                bull_score += 2
                buildup_type = "Put Writing"
            else:
                # Aggressive put buying → hedging / bearish
                bear_score  += 1
                buildup_type = buildup_type or "Put Buying"
            key_strike    = int(top["strike"])
            key_oi_change = int(top["put_chg"])
            label         = "Put writing" if vol_ratio < 1.5 else "Put buying"
            top_signals.append(
                f"{label} at {_strike_fmt(top['strike'])} (+{_oi_fmt(top['put_chg'])} OI)"
            )

    # 2. Call writing at or above spot (bearish)
    call_builds_above = sorted(
        [d for d in deltas if d["above"] and d["call_chg"] > 0],
        key=lambda d: d["call_chg"], reverse=True,
    )
    if call_builds_above:
        top = call_builds_above[0]
        share = top["call_chg"] / total_call_build if total_call_build > 0 else 0
        if share > 0.25:
            vol_ratio = top["call_vol"] / (top["call_chg"] + 1)
            if vol_ratio < 1.5:
                bear_score   += 2
                buildup_type  = buildup_type or "Call Writing"
            else:
                bear_score   += 1
                buildup_type  = buildup_type or "Call Buying"
            if key_strike is None:
                key_strike    = int(top["strike"])
                key_oi_change = int(top["call_chg"])
            label = "Call writing" if vol_ratio < 1.5 else "Call buying"
            top_signals.append(
                f"{label} at {_strike_fmt(top['strike'])} (+{_oi_fmt(top['call_chg'])} OI)"
            )

    # 3. Call unwinding above spot → bears covering → bullish
    call_unwinds = sorted(
        [d for d in deltas if d["above"] and d["call_chg"] < 0],
        key=lambda d: d["call_chg"],
    )
    if call_unwinds:
        top   = call_unwinds[0]
        share = abs(top["call_chg"]) / total_call_unwind if total_call_unwind > 0 else 0
        if share > 0.3:
            bull_score += 1
            buildup_type = buildup_type or "Call Unwinding"
            if key_strike is None:
                key_strike    = int(top["strike"])
                key_oi_change = int(top["call_chg"])
            top_signals.append(
                f"Call unwinding at {_strike_fmt(top['strike'])} ({_oi_fmt(top['call_chg'])} OI)"
            )

    # 4. Put unwinding below spot → longs/writers exiting → bearish
    put_unwinds = sorted(
        [d for d in deltas if d["below"] and d["put_chg"] < 0],
        key=lambda d: d["put_chg"],
    )
    if put_unwinds:
        top   = put_unwinds[0]
        share = abs(top["put_chg"]) / total_put_unwind if total_put_unwind > 0 else 0
        if share > 0.3:
            bear_score += 1
            buildup_type = buildup_type or "Put Unwinding"
            if key_strike is None:
                key_strike    = int(top["strike"])
                key_oi_change = int(top["put_chg"])
            top_signals.append(
                f"Put unwinding at {_strike_fmt(top['strike'])} ({_oi_fmt(top['put_chg'])} OI)"
            )

    # ── Resolve signal ────────────────────────────────────────────────────────
    total = bull_score + bear_score
    if total == 0 or not top_signals:
        return _no_signal(symbol, "No significant OI activity in the last 10 min")

    net = bull_score - bear_score

    if net >= 2:
        quick_signal = "Buy CE"
        strength     = "Strong" if net >= 3 else "Moderate"
        summary      = " · ".join(top_signals)
        reason       = f"{summary} → Bullish buildup"
    elif net <= -2:
        quick_signal = "Buy PE"
        strength     = "Strong" if net <= -3 else "Moderate"
        summary      = " · ".join(top_signals)
        reason       = f"{summary} → Bearish buildup"
    elif net > 0:
        quick_signal = "Watch"
        strength     = "Weak"
        reason       = " · ".join(top_signals) + " → Slight bullish tilt, wait for confirmation"
    elif net < 0:
        quick_signal = "Watch"
        strength     = "Weak"
        reason       = " · ".join(top_signals) + " → Slight bearish tilt, wait for confirmation"
    else:
        return _no_signal(symbol, " · ".join(top_signals) + " → Balanced OI activity, no edge")

    logger.debug(
        "quick_signal_generated",
        symbol=symbol,
        signal=quick_signal,
        bull=bull_score,
        bear=bear_score,
    )

    return {
        "symbol":         symbol,
        "quick_signal":   quick_signal,
        "buildup_type":   buildup_type,
        "key_strike":     key_strike,
        "key_oi_change":  key_oi_change,
        "strength":       strength,
        "bull_score":     bull_score,
        "bear_score":     bear_score,
        "reason":         reason,
        "top_signals":    top_signals,
        "window_minutes": WINDOW_MINUTES,
        "news_boost":     False,   # placeholder: set True when news integration fires
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }
