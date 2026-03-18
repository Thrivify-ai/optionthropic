"""
Core options analysis — Put-Call Ratio, support/resistance detection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chain_snapshot import ChainSnapshot
from app.logging_config import get_logger

logger = get_logger(__name__)


# ─── Put-Call Ratio ────────────────────────────────────────────────────────────


async def compute_pcr(
    session: AsyncSession, symbol: str, lookback_snapshots: int = 5
) -> dict[str, Any]:
    """
    Returns PCR (OI-based), PCR (volume-based), and a 5-period rolling average.
    """
    stmt = (
        select(
            ChainSnapshot.strike,
            func.sum(ChainSnapshot.call_oi).label("total_call_oi"),
            func.sum(ChainSnapshot.put_oi).label("total_put_oi"),
            func.sum(ChainSnapshot.call_volume).label("total_call_vol"),
            func.sum(ChainSnapshot.put_volume).label("total_put_vol"),
        )
        .where(ChainSnapshot.symbol == symbol)
        .group_by(ChainSnapshot.strike)
        .order_by(ChainSnapshot.strike)
    )

    rows = (await session.execute(stmt)).all()
    if not rows:
        return {"pcr_oi": None, "pcr_volume": None, "sentiment": "NEUTRAL"}

    df = pd.DataFrame(rows, columns=["strike", "call_oi", "put_oi", "call_vol", "put_vol"])
    total_call_oi = df["call_oi"].sum()
    total_put_oi = df["put_oi"].sum()
    total_call_vol = df["call_vol"].sum()
    total_put_vol = df["put_vol"].sum()

    pcr_oi = round(total_put_oi / total_call_oi, 4) if total_call_oi else None
    pcr_vol = round(total_put_vol / total_call_vol, 4) if total_call_vol else None

    sentiment = "NEUTRAL"
    if pcr_oi is not None:
        if pcr_oi > 1.3:
            sentiment = "BULLISH"
        elif pcr_oi < 0.7:
            sentiment = "BEARISH"

    return {
        "symbol": symbol,
        "pcr_oi": pcr_oi,
        "pcr_volume": pcr_vol,
        "total_call_oi": int(total_call_oi),
        "total_put_oi": int(total_put_oi),
        "sentiment": sentiment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Support / Resistance ──────────────────────────────────────────────────────


async def compute_support_resistance(
    session: AsyncSession, symbol: str, top_n: int = 5
) -> dict[str, Any]:
    """
    Identifies key support (high put OI) and resistance (high call OI) strikes.
    Uses the latest snapshot only.
    """
    latest_ts_stmt = (
        select(func.max(ChainSnapshot.timestamp))
        .where(ChainSnapshot.symbol == symbol)
    )
    latest_ts = (await session.execute(latest_ts_stmt)).scalar()
    if not latest_ts:
        return {"support": [], "resistance": [], "symbol": symbol}

    stmt = (
        select(ChainSnapshot)
        .where(
            ChainSnapshot.symbol == symbol,
            ChainSnapshot.timestamp == latest_ts,
        )
        .order_by(ChainSnapshot.strike)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return {"support": [], "resistance": [], "symbol": symbol}

    df = pd.DataFrame(
        [
            {
                "strike": float(r.strike),
                "call_oi": int(r.call_oi),
                "put_oi": int(r.put_oi),
                "underlying_price": float(r.underlying_price),
            }
            for r in rows
        ]
    )

    valid = df["underlying_price"][df["underlying_price"] > 0]
    underlying = float(valid.median() if not valid.empty else df["underlying_price"].iloc[0])

    # Resistance = strikes above underlying with highest call OI
    resistance_df = df[df["strike"] >= underlying].nlargest(top_n, "call_oi")
    # Support = strikes below underlying with highest put OI
    support_df = df[df["strike"] <= underlying].nlargest(top_n, "put_oi")

    return {
        "symbol": symbol,
        "underlying_price": float(underlying),
        "resistance": [
            {"strike": float(r["strike"]), "call_oi": int(r["call_oi"])}
            for _, r in resistance_df.iterrows()
        ],
        "support": [
            {"strike": float(r["strike"]), "put_oi": int(r["put_oi"])}
            for _, r in support_df.iterrows()
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
