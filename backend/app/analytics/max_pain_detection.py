"""
Max pain detection.

Max pain = the strike at which option writers (sellers) suffer the least
total financial loss upon expiry.

Algorithm:
  For each candidate strike S:
    loss(S) = Σ_calls  max(0, S - K) × call_OI(K)   [in-the-money calls]
            + Σ_puts   max(0, K - S) × put_OI(K)    [in-the-money puts]
  max_pain_strike = argmin loss(S)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chain_snapshot import ChainSnapshot
from app.logging_config import get_logger

logger = get_logger(__name__)


def _compute_max_pain(df: pd.DataFrame) -> float:
    strikes = df["strike"].unique()
    min_loss = float("inf")
    max_pain = strikes[0]

    for s in strikes:
        call_loss = df.apply(lambda r: max(0.0, s - r["strike"]) * r["call_oi"], axis=1).sum()
        put_loss = df.apply(lambda r: max(0.0, r["strike"] - s) * r["put_oi"], axis=1).sum()
        total = call_loss + put_loss
        if total < min_loss:
            min_loss = total
            max_pain = s

    return float(max_pain)


async def compute_max_pain(
    session: AsyncSession,
    symbol: str,
    expiry: date | None = None,
) -> dict[str, Any]:
    latest_ts_stmt = (
        select(func.max(ChainSnapshot.timestamp))
        .where(ChainSnapshot.symbol == symbol)
    )
    latest_ts = (await session.execute(latest_ts_stmt)).scalar()
    if not latest_ts:
        return {"symbol": symbol, "max_pain_strike": None}

    stmt = select(ChainSnapshot).where(
        ChainSnapshot.symbol == symbol,
        ChainSnapshot.timestamp == latest_ts,
    )
    if expiry:
        stmt = stmt.where(ChainSnapshot.expiry == expiry)

    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return {"symbol": symbol, "max_pain_strike": None}

    df = pd.DataFrame(
        [
            {
                "strike": float(r.strike),
                "call_oi": int(r.call_oi),
                "put_oi": int(r.put_oi),
                "expiry": r.expiry,
                "underlying_price": float(r.underlying_price),
            }
            for r in rows
        ]
    )

    valid = df["underlying_price"][df["underlying_price"] > 0]
    spot = float(valid.median() if not valid.empty else df["underlying_price"].iloc[0])

    # Compute per expiry
    results = []
    for exp, group in df.groupby("expiry"):
        mp = _compute_max_pain(group)
        deviation_pct = round((mp - spot) / spot * 100, 2)
        results.append(
            {
                "expiry": str(exp),
                "max_pain_strike": mp,
                "deviation_from_spot_pct": deviation_pct,
            }
        )

    nearest = min(results, key=lambda x: x["max_pain_strike"])

    return {
        "symbol": symbol,
        "underlying_price": float(spot),
        "max_pain_strike": nearest["max_pain_strike"],
        "deviation_from_spot_pct": nearest["deviation_from_spot_pct"],
        "by_expiry": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
