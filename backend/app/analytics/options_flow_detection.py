"""
Smart money / options flow detection.

Classifies recent large-premium trades as:
  SWEEP  — aggressive market-order execution across multiple strikes
  BLOCK  — single large ticket at one strike (institutional)
  UNUSUAL — volume >> OI (fresh positioning well above normal)
  NORMAL — regular retail flow

Uses latest OptionsSnapshot data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.options_snapshot import OptionsSnapshot
from app.models.options_flow import OptionsFlow, FlowSide, FlowType
from app.logging_config import get_logger

logger = get_logger(__name__)

# Thresholds
BLOCK_PREMIUM_THRESHOLD = 5_000_000      # ₹50 lakh premium
UNUSUAL_VOLUME_OI_RATIO = 0.5            # volume > 50 % of OI → unusual
SWEEP_STRIKES_COUNT = 3                  # multiple strikes hit


def _classify_flow(
    volume: int,
    oi: int,
    premium: float,
    strike_count: int = 1,
) -> FlowType:
    if strike_count >= SWEEP_STRIKES_COUNT:
        return FlowType.SWEEP
    if premium >= BLOCK_PREMIUM_THRESHOLD:
        return FlowType.BLOCK
    if oi > 0 and (volume / oi) >= UNUSUAL_VOLUME_OI_RATIO:
        return FlowType.UNUSUAL
    return FlowType.NORMAL


async def detect_options_flow(
    session: AsyncSession, symbol: str, top_n: int = 20
) -> dict[str, Any]:
    latest_ts_stmt = (
        select(func.max(OptionsSnapshot.timestamp))
        .where(OptionsSnapshot.symbol == symbol)
    )
    latest_ts = (await session.execute(latest_ts_stmt)).scalar()
    if not latest_ts:
        return {"symbol": symbol, "flows": []}

    stmt = (
        select(OptionsSnapshot)
        .where(
            OptionsSnapshot.symbol == symbol,
            OptionsSnapshot.timestamp == latest_ts,
        )
        .order_by(desc(OptionsSnapshot.volume))
        .limit(100)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return {"symbol": symbol, "flows": []}

    df = pd.DataFrame(
        [
            {
                "strike": float(r.strike),
                "option_type": r.option_type,
                "oi": int(r.oi),
                "volume": int(r.volume),
                "last_price": float(r.last_price),
                "underlying_price": float(r.underlying_price),
            }
            for r in rows
        ]
    )

    valid = df["underlying_price"][df["underlying_price"] > 0]
    spot = float(valid.median() if not valid.empty else df["underlying_price"].iloc[0])
    df["premium"] = df["volume"] * df["last_price"] * 50  # lot size approximation

    # Count how many strikes are active (sweep proxy)
    active_strikes = df[df["volume"] > 1000]["strike"].nunique()

    flows = []
    new_flow_records = []
    for _, row in df.head(top_n).iterrows():
        flow_type = _classify_flow(
            int(row["volume"]),
            int(row["oi"]),
            float(row["premium"]),
            active_strikes,
        )
        side = FlowSide.BUY if row["option_type"] == "CE" else FlowSide.SELL

        flows.append(
            {
                "strike": float(row["strike"]),
                "option_type": str(row["option_type"].value if hasattr(row["option_type"], "value") else row["option_type"]),
                "side": side.value,
                "volume": int(row["volume"]),
                "premium": round(float(row["premium"]), 2),
                "flow_type": flow_type.value,
                "distance_from_spot_pct": round((row["strike"] - spot) / spot * 100, 2),
            }
        )

        new_flow_records.append(
            OptionsFlow(
                symbol=symbol,
                strike=row["strike"],
                side=side,
                volume=int(row["volume"]),
                premium=row["premium"],
                flow_type=flow_type,
                timestamp=latest_ts,
            )
        )

    session.add_all(new_flow_records)
    await session.flush()

    summary = {
        "total_call_premium": round(float(df[df["option_type"] == "CE"]["premium"].sum()), 2),
        "total_put_premium": round(float(df[df["option_type"] == "PE"]["premium"].sum()), 2),
    }
    summary["premium_ratio"] = round(
        summary["total_put_premium"] / (summary["total_call_premium"] + 1), 4
    )

    return {
        "symbol": symbol,
        "underlying_price": float(spot),
        "flows": flows,
        "summary": summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
