"""
Liquidity trap detection.

A liquidity trap is a strike where:
  - OI is very high relative to volume (low turnover = stale open interest)
  - If price approaches these strikes, large unwinding can trigger sharp moves

Trap score = OI / (volume + 1)  — higher means more illiquid concentration
Threshold: top 10 % of scores flagged as traps
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


async def detect_liquidity_traps(
    session: AsyncSession, symbol: str, top_n: int = 5
) -> dict[str, Any]:
    latest_ts_stmt = (
        select(func.max(ChainSnapshot.timestamp))
        .where(ChainSnapshot.symbol == symbol)
    )
    latest_ts = (await session.execute(latest_ts_stmt)).scalar()
    if not latest_ts:
        return {"symbol": symbol, "traps": []}

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
        return {"symbol": symbol, "traps": []}

    df = pd.DataFrame(
        [
            {
                "strike": float(r.strike),
                "call_oi": int(r.call_oi),
                "put_oi": int(r.put_oi),
                "call_volume": int(r.call_volume),
                "put_volume": int(r.put_volume),
                "underlying_price": float(r.underlying_price),
            }
            for r in rows
        ]
    )

    valid = df["underlying_price"][df["underlying_price"] > 0]
    spot = float(valid.median() if not valid.empty else df["underlying_price"].iloc[0])

    df["total_oi"] = df["call_oi"] + df["put_oi"]
    df["total_volume"] = df["call_volume"] + df["put_volume"]
    df["trap_score"] = df["total_oi"] / (df["total_volume"] + 1)

    # Only look within ±5 % of spot
    band = spot * 0.05
    nearby = df[(df["strike"] >= spot - band) & (df["strike"] <= spot + band)].copy()

    if nearby.empty:
        nearby = df.copy()

    threshold = nearby["trap_score"].quantile(0.9)
    traps_df = nearby[nearby["trap_score"] >= threshold].nlargest(top_n, "trap_score")

    traps = []
    for _, row in traps_df.iterrows():
        side = "CALL_TRAP" if row["call_oi"] > row["put_oi"] else "PUT_TRAP"
        distance_pct = round((row["strike"] - spot) / spot * 100, 2)
        traps.append(
            {
                "strike": float(row["strike"]),
                "trap_score": round(float(row["trap_score"]), 2),
                "total_oi": int(row["total_oi"]),
                "total_volume": int(row["total_volume"]),
                "side": side,
                "distance_from_spot_pct": distance_pct,
            }
        )

    return {
        "symbol": symbol,
        "underlying_price": float(spot),
        "traps": traps,
        "trap_threshold_score": round(float(threshold), 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
