"""
Intraday positioning shift detection.

Compares the two most recent consecutive chain snapshots.
Classifies OI changes at each strike as:
  LONG_BUILDUP    : price ↑ and OI ↑
  SHORT_COVERING  : price ↑ and OI ↓
  SHORT_BUILDUP   : price ↓ and OI ↑
  LONG_UNWINDING  : price ↓ and OI ↓
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chain_snapshot import ChainSnapshot
from app.models.options_snapshot import OptionsSnapshot
from app.logging_config import get_logger

logger = get_logger(__name__)

_SHIFT_LABELS = {
    (True, True): "LONG_BUILDUP",
    (True, False): "SHORT_COVERING",
    (False, True): "SHORT_BUILDUP",
    (False, False): "LONG_UNWINDING",
}


def _classify(price_up: bool, oi_up: bool) -> str:
    return _SHIFT_LABELS[(price_up, oi_up)]


async def detect_positioning_shifts(
    session: AsyncSession, symbol: str, top_n: int = 10
) -> dict[str, Any]:
    # Get the two most recent distinct timestamps
    ts_stmt = (
        select(ChainSnapshot.timestamp)
        .where(ChainSnapshot.symbol == symbol)
        .distinct()
        .order_by(desc(ChainSnapshot.timestamp))
        .limit(2)
    )
    timestamps = (await session.execute(ts_stmt)).scalars().all()

    if len(timestamps) < 2:
        return {"symbol": symbol, "shifts": [], "message": "Insufficient history"}

    latest_ts, prev_ts = timestamps[0], timestamps[1]

    async def _load_snapshot(ts) -> pd.DataFrame:
        stmt = (
            select(
                ChainSnapshot.strike,
                ChainSnapshot.call_oi,
                ChainSnapshot.put_oi,
                ChainSnapshot.underlying_price,
            )
            .where(
                ChainSnapshot.symbol == symbol,
                ChainSnapshot.timestamp == ts,
            )
        )
        rows = (await session.execute(stmt)).all()
        df = pd.DataFrame(rows, columns=["strike", "call_oi", "put_oi", "underlying_price"])
        df["strike"] = df["strike"].astype(float)
        df["call_oi"] = df["call_oi"].astype(int)
        df["put_oi"] = df["put_oi"].astype(int)
        df["underlying_price"] = df["underlying_price"].astype(float)
        return df

    df_latest = await _load_snapshot(latest_ts)
    df_prev = await _load_snapshot(prev_ts)

    merged = df_latest.merge(
        df_prev,
        on="strike",
        suffixes=("_now", "_prev"),
    )
    if merged.empty:
        return {"symbol": symbol, "shifts": []}

    valid_now = df_latest["underlying_price"][df_latest["underlying_price"] > 0]
    valid_prev = df_prev["underlying_price"][df_prev["underlying_price"] > 0]
    spot_now = float(valid_now.median() if not valid_now.empty else df_latest["underlying_price"].iloc[0])
    spot_prev = float(valid_prev.median() if not valid_prev.empty else df_prev["underlying_price"].iloc[0])
    price_up = spot_now >= spot_prev

    merged["call_oi_change"] = merged["call_oi_now"] - merged["call_oi_prev"]
    merged["put_oi_change"] = merged["put_oi_now"] - merged["put_oi_prev"]
    merged["call_signal"] = merged["call_oi_change"].apply(
        lambda x: _classify(price_up, x >= 0)
    )
    merged["put_signal"] = merged["put_oi_change"].apply(
        lambda x: _classify(price_up, x >= 0)
    )

    significant = merged[
        (merged["call_oi_change"].abs() > 0) | (merged["put_oi_change"].abs() > 0)
    ].copy()
    significant["total_change"] = (
        significant["call_oi_change"].abs() + significant["put_oi_change"].abs()
    )
    top = significant.nlargest(top_n, "total_change")

    shifts = []
    for _, row in top.iterrows():
        shifts.append(
            {
                "strike": float(row["strike"]),
                "call_oi_change": int(row["call_oi_change"]),
                "put_oi_change": int(row["put_oi_change"]),
                "call_signal": row["call_signal"],
                "put_signal": row["put_signal"],
            }
        )

    return {
        "symbol": symbol,
        "underlying_price": float(spot_now),
        "underlying_change": round(float(spot_now - spot_prev), 2),
        "price_direction": "UP" if price_up else "DOWN",
        "shifts": shifts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
