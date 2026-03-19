"""
Core options analysis — Put-Call Ratio, support/resistance detection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.foundation_utils import pcr_sentiment_from_value
from app.models.chain_snapshot import ChainSnapshot
from app.logging_config import get_logger

logger = get_logger(__name__)


# ─── Put-Call Ratio ────────────────────────────────────────────────────────────


async def compute_pcr(
    session: AsyncSession, symbol: str, lookback_snapshots: int = 5
) -> dict[str, Any]:
    """
    Returns PCR for the latest snapshot and a recent rolling average.
    """
    latest_ts_stmt = (
        select(func.max(ChainSnapshot.timestamp))
        .where(ChainSnapshot.symbol == symbol)
    )
    latest_ts = (await session.execute(latest_ts_stmt)).scalar()
    if not latest_ts:
        return {"pcr_oi": None, "pcr_volume": None, "sentiment": "NEUTRAL"}

    latest_stmt = (
        select(
            ChainSnapshot.strike,
            func.sum(ChainSnapshot.call_oi).label("total_call_oi"),
            func.sum(ChainSnapshot.put_oi).label("total_put_oi"),
            func.sum(ChainSnapshot.call_volume).label("total_call_vol"),
            func.sum(ChainSnapshot.put_volume).label("total_put_vol"),
        )
        .where(
            ChainSnapshot.symbol == symbol,
            ChainSnapshot.timestamp == latest_ts,
        )
        .group_by(ChainSnapshot.strike)
        .order_by(ChainSnapshot.strike)
    )

    rows = (await session.execute(latest_stmt)).all()
    if not rows:
        return {"pcr_oi": None, "pcr_volume": None, "sentiment": "NEUTRAL"}

    df = pd.DataFrame(rows, columns=["strike", "call_oi", "put_oi", "call_vol", "put_vol"])
    total_call_oi = df["call_oi"].sum()
    total_put_oi = df["put_oi"].sum()
    total_call_vol = df["call_vol"].sum()
    total_put_vol = df["put_vol"].sum()

    pcr_oi = round(total_put_oi / total_call_oi, 4) if total_call_oi else None
    pcr_vol = round(total_put_vol / total_call_vol, 4) if total_call_vol else None

    rolling_timestamps_stmt = (
        select(ChainSnapshot.timestamp)
        .where(ChainSnapshot.symbol == symbol)
        .distinct()
        .order_by(ChainSnapshot.timestamp.desc())
        .limit(max(1, lookback_snapshots))
    )
    timestamps = list((await session.execute(rolling_timestamps_stmt)).scalars().all())

    pcr_history: list[float] = []
    if timestamps:
        rolling_stmt = (
            select(
                ChainSnapshot.timestamp,
                func.sum(ChainSnapshot.call_oi).label("total_call_oi"),
                func.sum(ChainSnapshot.put_oi).label("total_put_oi"),
            )
            .where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp.in_(timestamps),
            )
            .group_by(ChainSnapshot.timestamp)
            .order_by(ChainSnapshot.timestamp.desc())
        )
        rolling_rows = (await session.execute(rolling_stmt)).all()
        for _, call_oi_sum, put_oi_sum in rolling_rows:
            if call_oi_sum:
                pcr_history.append(float(put_oi_sum or 0) / float(call_oi_sum))

    pcr_oi_ma = round(sum(pcr_history) / len(pcr_history), 4) if pcr_history else None
    sentiment = pcr_sentiment_from_value(pcr_oi)

    return {
        "symbol": symbol,
        "pcr_oi": pcr_oi,
        "pcr_volume": pcr_vol,
        "pcr_oi_ma": pcr_oi_ma,
        "total_call_oi": int(total_call_oi),
        "total_put_oi": int(total_put_oi),
        "sentiment": sentiment,
        "latest_snapshot_at": latest_ts.isoformat() if hasattr(latest_ts, "isoformat") else latest_ts,
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
