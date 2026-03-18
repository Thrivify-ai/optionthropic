"""
Quick Signal Engine — high-speed intraday options signal.

Goal: Detect 30–40 point fast intraday moves (or equivalent) in NIFTY / BANKNIFTY / SENSEX.

Primary trigger: momentum-based (1m and 3m) — price moved 30–40 pts in direction.
  - NIFTY: ±35 pts (index ~24k)
  - BANKNIFTY: ±80 pts (index ~52k, moves ~2.3× NIFTY)
  - SENSEX: ±100 pts (index ~80k, moves ~3× NIFTY)

Pipeline:
  1. Momentum — 1m and 3m price change vs per-symbol threshold
  2. Liquidity trap filter — ignore reversals after breakout
  3. OI / Volume — optional confirmation; momentum alone can fire
  4. Breakout — bonus if at S/R; not required

Designed to be called on-demand; no background job or DB writes needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models.chain_snapshot import ChainSnapshot

logger = get_logger(__name__)


# ─── Per-symbol thresholds (30–40 pt equivalent) ──────────────────────────────
# bull_mom/bear_mom: 1-minute move threshold
# mom_3m: 3-minute move threshold — catches sustained moves (e.g. 100 pts over 2–3 min)
#         when 1m window shows less

_SYMBOL_CONFIG: dict[str, dict] = {
    "NIFTY":     {"bull_mom":  35, "bear_mom":  -35, "mom_3m":  25, "band_pct": 0.020},
    "BANKNIFTY": {"bull_mom":  80, "bear_mom":  -80, "mom_3m":  55, "band_pct": 0.020},
    "SENSEX":    {"bull_mom":  60, "bear_mom":  -60, "mom_3m":  50, "band_pct": 0.015},
}
_DEFAULT_CONFIG: dict[str, Any] = {"bull_mom": 40, "bear_mom": -40, "mom_3m": 30, "band_pct": 0.020}
_VOLUME_SPIKE_RATIO = 1.5   # current-minute volume must exceed 1.5× avg minute volume


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _cfg(symbol: str) -> dict:
    return _SYMBOL_CONFIG.get(symbol.upper(), _DEFAULT_CONFIG)


def _wait(symbol: str, reason: str,
          support: Optional[float] = None,
          resistance: Optional[float] = None,
          current_price: Optional[float] = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "symbol":       symbol,
        "quick_signal": "Wait",
        "momentum":     None,
        "volume_spike": False,
        "breakout":     False,
        "breakdown":    False,
        "oi_confirmed": False,
        "support":      support,
        "resistance":   resistance,
        "reason":       reason,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }
    if current_price is not None:
        out["current_price"] = round(current_price, 2)
    return out


async def _latest_timestamps(session: AsyncSession,
                              symbol: str, n: int = 7) -> list:
    """Return up to n most-recent distinct timestamps, newest first."""
    rows = (
        await session.execute(
            select(func.distinct(ChainSnapshot.timestamp))
            .where(ChainSnapshot.symbol == symbol)
            .order_by(desc(ChainSnapshot.timestamp))
            .limit(n)
        )
    ).scalars().all()
    return sorted(rows, reverse=True)


async def _snap(session: AsyncSession,
                symbol: str, ts) -> Optional[dict]:
    """Return aggregated price + OI + volume at a single timestamp."""
    price = (
        await session.execute(
            select(ChainSnapshot.underlying_price)
            .where(ChainSnapshot.symbol == symbol,
                   ChainSnapshot.timestamp == ts)
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
        "price":       float(price),
        "call_oi":     float(agg[0] or 0),
        "put_oi":      float(agg[1] or 0),
        "call_volume": float(agg[2] or 0),
        "put_volume":  float(agg[3] or 0),
        "total_vol":   total_vol,
    }


async def _support_resistance(session: AsyncSession, symbol: str,
                               ts, spot: float,
                               band_pct: float) -> tuple[Optional[float], Optional[float]]:
    """Nearest put-OI wall (support) and call-OI wall (resistance)."""
    band = spot * band_pct
    rows = (
        await session.execute(
            select(ChainSnapshot)
            .where(ChainSnapshot.symbol == symbol,
                   ChainSnapshot.timestamp == ts)
        )
    ).scalars().all()

    support = resistance = None
    if rows and spot > 0 and band > 0:
        below = [r for r in rows
                 if float(r.strike) <= spot
                 and abs(float(r.strike) - spot) <= band]
        above = [r for r in rows
                 if float(r.strike) >= spot
                 and abs(float(r.strike) - spot) <= band]
        if below:
            support    = float(max(below, key=lambda r: r.put_oi).strike)
        if above:
            resistance = float(max(above, key=lambda r: r.call_oi).strike)
    return support, resistance


# ─── Main engine ─────────────────────────────────────────────────────────────

async def run_quick_signal_engine(session: AsyncSession,
                                   symbol: str) -> dict[str, Any]:
    """
    Six-step quick signal engine.

    Returns a dict with quick_signal ∈ {"Buy CE", "Buy PE", "Wait"}.
    """
    symbol = symbol.upper()
    cfg    = _cfg(symbol)

    # ── Collect timestamps ────────────────────────────────────────────────────
    timestamps = await _latest_timestamps(session, symbol, n=7)
    if len(timestamps) < 2:
        return _wait(symbol, "Insufficient data (need ≥ 2 snapshots)")

    ts_now = timestamps[0]

    # ~1-minute-ago: first timestamp at least 55 s before ts_now
    ts_1m = next(
        (t for t in timestamps[1:] if (ts_now - t).total_seconds() >= 55),
        timestamps[1],
    )
    # ~3-minute-ago
    ts_3m = next(
        (t for t in timestamps[1:] if (ts_now - t).total_seconds() >= 175),
        None,
    )

    # ── Snapshots ─────────────────────────────────────────────────────────────
    curr = await _snap(session, symbol, ts_now)
    if not curr or curr["price"] == 0:
        return _wait(symbol, "No current price data", current_price=curr["price"] if curr else None)

    prev_1m = await _snap(session, symbol, ts_1m)
    if not prev_1m:
        return _wait(symbol, "Cannot read 1-min-ago snapshot", current_price=curr["price"])

    spot = curr["price"]

    # ── Support / Resistance ──────────────────────────────────────────────────
    support, resistance = await _support_resistance(
        session, symbol, ts_now, spot, cfg["band_pct"])

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 1 — Momentum
    # ═══════════════════════════════════════════════════════════════════════════
    momentum_1m    = round(spot - prev_1m["price"], 2)
    strong_bullish = momentum_1m >= cfg["bull_mom"]
    strong_bearish = momentum_1m <= cfg["bear_mom"]

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 2 — Volume spike
    # ═══════════════════════════════════════════════════════════════════════════
    # Build per-minute volume deltas over last 5 available pairs
    minute_vols: list[float] = []
    for i in range(min(5, len(timestamps) - 1)):
        a = await _snap(session, symbol, timestamps[i])
        b = await _snap(session, symbol, timestamps[i + 1])
        if a and b:
            delta = a["total_vol"] - b["total_vol"]
            if delta > 0:
                minute_vols.append(delta)

    # Current minute's volume delta
    current_min_vol = max(0.0, curr["total_vol"] - prev_1m["total_vol"])
    avg_min_vol     = (sum(minute_vols) / len(minute_vols)) if minute_vols else 0.0
    volume_spike    = avg_min_vol > 0 and current_min_vol >= _VOLUME_SPIKE_RATIO * avg_min_vol

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 3 — Breakout / breakdown
    # ═══════════════════════════════════════════════════════════════════════════
    bullish_breakout  = resistance is not None and spot > resistance * 1.001
    bearish_breakdown = support    is not None and spot < support    * 0.999

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 4 — OI confirmation
    # ═══════════════════════════════════════════════════════════════════════════
    call_oi_delta = curr["call_oi"] - prev_1m["call_oi"]
    put_oi_delta  = curr["put_oi"]  - prev_1m["put_oi"]

    # Bullish: call shorts covering (call OI falling) while put OI stable/growing
    oi_bullish = call_oi_delta < 0 and put_oi_delta >= 0
    # Bearish: put shorts covering (put OI falling) while call OI stable/growing
    oi_bearish = put_oi_delta < 0 and call_oi_delta >= 0

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 5 — Liquidity trap filter
    # Breakout happened 1+ min ago AND price is now reversing back
    # ═══════════════════════════════════════════════════════════════════════════
    trap_bull = (
        bullish_breakout
        and resistance is not None
        and prev_1m["price"] > resistance   # already broke out previously
        and spot < prev_1m["price"]         # now falling back
    )
    trap_bear = (
        bearish_breakdown
        and support is not None
        and prev_1m["price"] < support      # already broke down previously
        and spot > prev_1m["price"]         # now bouncing back up
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 6 — Final decision (fast + predictive)
    #
    # The original strict design (ALL gates) is good for low false-positives but
    # can miss fast 40–80 point bursts. We keep the strict breakout trigger,
    # and add a *pre-break prediction* when price is compressing into S/R with
    # strong minute momentum + volume spike + OI confirmation.
    # ═══════════════════════════════════════════════════════════════════════════

    # 3-minute context (optional but improves quality)
    momentum_3m = None
    if ts_3m is not None:
        prev_3m = await _snap(session, symbol, ts_3m)
        if prev_3m and prev_3m["price"]:
            momentum_3m = round(spot - prev_3m["price"], 2)

    # Liquidity-trap: breakout occurred but price snapped back within ~2 minutes
    # (approximation using the 1m-ago snapshot)
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

    # Pre-break proximity threshold (how close we are to S/R before breaking)
    proximity_pct = 0.0015  # 0.15%
    near_resistance = resistance is not None and (resistance * (1 - proximity_pct) <= spot <= resistance)
    near_support    = support    is not None and (support    <= spot <= support * (1 + proximity_pct))

    # Predictive momentum: either 1m >= threshold OR 3m >= threshold with 1m same direction.
    # Catches moves like "100 pts over 2–3 min" when 1m window shows ~50 pts.
    mom_3m_thresh = cfg.get("mom_3m", cfg["bull_mom"] * 0.7)
    strong_bullish_3m = momentum_3m is not None and momentum_3m >= mom_3m_thresh
    strong_bearish_3m = momentum_3m is not None and momentum_3m <= -mom_3m_thresh

    bullish_trend_ok = (
        (strong_bullish and (momentum_3m is None or momentum_3m > 0))
        or (strong_bullish_3m and momentum_1m > 0)
    )
    bearish_trend_ok = (
        (strong_bearish and (momentum_3m is None or momentum_3m < 0))
        or (strong_bearish_3m and momentum_1m < 0)
    )

    # Target move for UI (30–40 pt goal)
    target_move = 35 if symbol == "NIFTY" else (80 if symbol == "BANKNIFTY" else 100)

    def _out(signal: str, breakout: bool, breakdown: bool, reason: str) -> dict[str, Any]:
        return {
            "symbol":        symbol,
            "quick_signal":  signal,
            "momentum":      momentum_1m,
            "momentum_3m":   momentum_3m,
            "volume_spike":  bool(volume_spike),
            "breakout":      bool(breakout),
            "breakdown":     bool(breakdown),
            "oi_confirmed":  bool(oi_bullish if signal == "Buy CE" else oi_bearish),
            "support":       support,
            "resistance":    resistance,
            "current_price": round(spot, 2),
            "target_move_points": target_move,
            "reason":        reason,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }

    # ── Momentum-first triggers (primary: 30–40 pt move detected) ─────────────
    # Fire when momentum ≥ threshold and 3m same direction; trap filter only.
    # OI/volume/breakout are bonuses for reason text, not required.
    if bullish_trend_ok and not trap_bull:
        ext = []
        if bullish_breakout:
            ext.append(f"breakout above {int(resistance):,}")
        if oi_bullish:
            ext.append("OI covering")
        if volume_spike:
            ext.append("volume spike")
        return _out(
            "Buy CE",
            breakout=bullish_breakout,
            breakdown=False,
            reason=(
                f"+{momentum_1m:.0f} pts (1m)" +
                (f", +{momentum_3m:.0f} (3m)" if momentum_3m is not None else "") +
                (" · " + " · ".join(ext) if ext else "") +
                f" → expect +{target_move} pts follow-through"
            ),
        )

    if bearish_trend_ok and not trap_bear:
        ext = []
        if bearish_breakdown:
            ext.append(f"breakdown below {int(support):,}")
        if oi_bearish:
            ext.append("OI covering")
        if volume_spike:
            ext.append("volume spike")
        return _out(
            "Buy PE",
            breakout=False,
            breakdown=bearish_breakdown,
            reason=(
                f"{momentum_1m:.0f} pts (1m)" +
                (f", {momentum_3m:.0f} (3m)" if momentum_3m is not None else "") +
                (" · " + " · ".join(ext) if ext else "") +
                f" → expect -{target_move} pts follow-through"
            ),
        )

    # ── Build informative Wait reason ─────────────────────────────────────────
    missing: list[str] = []
    if trap_bull or trap_bear:
        missing.append("liquidity trap (reversal after move)")
    if not bullish_trend_ok and not bearish_trend_ok:
        m1 = f"1m {momentum_1m:+.0f} (need ±{cfg['bull_mom']})"
        m3 = f"3m {momentum_3m:+.0f} (need ±{int(mom_3m_thresh)})" if momentum_3m is not None else ""
        missing.append(f"momentum: {m1}" + (f" · {m3}" if m3 else ""))
    elif momentum_3m is not None and (
        (strong_bullish and momentum_3m <= 0) or (strong_bearish and momentum_3m >= 0)
    ):
        missing.append("3m momentum opposite to 1m (not sustained)")

    reason = "Waiting — " + ", ".join(missing) if missing else "No significant move detected"

    return _wait(symbol, reason, support=support, resistance=resistance, current_price=spot)
