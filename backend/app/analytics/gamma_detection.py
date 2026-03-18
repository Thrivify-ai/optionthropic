"""
Gamma wall detection.

Gamma is approximated as OI × (delta sensitivity proxy).
For ATM options delta ≈ 0.5; we use a simplified Gaussian model:
  gamma_proxy = OI × exp(-0.5 × ((strike - spot) / (spot × 0.01))²)

Call wall  = strike with highest call gamma_proxy above spot
Put wall   = strike with highest put  gamma_proxy below spot
Net gamma  = call_gamma - put_gamma per strike (positive = upward pressure)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chain_snapshot import ChainSnapshot
from app.logging_config import get_logger

logger = get_logger(__name__)


def _gamma_proxy(oi: float, strike: float, spot: float) -> float:
    """Simplified gamma proxy using Gaussian distance from ATM."""
    sigma = spot * 0.01  # 1 % of spot as width
    return oi * math.exp(-0.5 * ((strike - spot) / sigma) ** 2)


async def compute_gamma_walls(
    session: AsyncSession, symbol: str
) -> dict[str, Any]:
    latest_ts_stmt = (
        select(func.max(ChainSnapshot.timestamp))
        .where(ChainSnapshot.symbol == symbol)
    )
    latest_ts = (await session.execute(latest_ts_stmt)).scalar()
    if not latest_ts:
        return {"symbol": symbol, "call_wall": None, "put_wall": None}

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
        return {"symbol": symbol, "call_wall": None, "put_wall": None}

    records = [
        {
            "strike": float(r.strike),
            "call_oi": int(r.call_oi),
            "put_oi": int(r.put_oi),
            "underlying_price": float(r.underlying_price),
        }
        for r in rows
    ]
    df = pd.DataFrame(records)
    valid_prices = df["underlying_price"][df["underlying_price"] > 0]
    if valid_prices.empty:
        return {"symbol": symbol, "call_wall": None, "put_wall": None, "chart_data": []}
    spot = float(valid_prices.median())

    df["call_gamma"] = df.apply(
        lambda row: _gamma_proxy(row["call_oi"], row["strike"], spot), axis=1
    )
    df["put_gamma"] = df.apply(
        lambda row: _gamma_proxy(row["put_oi"], row["strike"], spot), axis=1
    )
    df["net_gamma"] = df["call_gamma"] - df["put_gamma"]

    call_wall_row = df[df["strike"] >= spot].nlargest(1, "call_gamma")
    put_wall_row = df[df["strike"] <= spot].nlargest(1, "put_gamma")

    support_row = df[df["strike"] < spot].nlargest(1, "put_oi")
    resistance_row = df[df["strike"] > spot].nlargest(1, "call_oi")

    # Top 10 strikes for chart data
    chart_data = (
        df.nlargest(15, "call_oi")[["strike", "call_oi", "put_oi", "net_gamma"]]
        .sort_values("strike")
        .to_dict(orient="records")
    )

    return {
        "symbol": symbol,
        "underlying_price": float(spot),
        "call_wall": float(call_wall_row["strike"].iloc[0]) if not call_wall_row.empty else None,
        "put_wall": float(put_wall_row["strike"].iloc[0]) if not put_wall_row.empty else None,
        "support_strike": float(support_row["strike"].iloc[0]) if not support_row.empty else None,
        "resistance_strike": float(resistance_row["strike"].iloc[0]) if not resistance_row.empty else None,
        "chart_data": chart_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
