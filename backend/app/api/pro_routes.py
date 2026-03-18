"""
Pro Signals API — live ticks, quick signals, swing signals, explanations.

New routes only. Does not modify existing APIs.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.commodity_signals import commodity_long_term_signal, commodity_quick_signal
from app.analytics.explanation_engine import explain_commodity_signal, explain_signal
from app.analytics.mcx_prices import get_mcx_prices
from app.analytics.pro_quick_signal import run_pro_quick_signal
from app.analytics.pro_swing_signal import get_pro_swing_signal
from app.api.auth_routes import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.tick_stream import get_latest_ticks

router = APIRouter(prefix="/api/pro", tags=["pro"])

SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"]
COMMODITIES = ["CRUDEOIL", "NATGAS", "GOLD", "SILVER"]


@router.get("/ticks")
async def get_pro_ticks(
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    Live tick data for NIFTY, BANKNIFTY, SENSEX.
    From WebSocket when available, else quote/DB fallback.
    """
    ticks = get_latest_ticks()
    if ticks:
        return {sym: {"price": d["price"], "change": d["change"]} for sym, d in ticks.items()}

    # Fallback: fetch from DB (chain_snapshot latest underlying_price)
    from sqlalchemy import select, desc
    from app.db.database import AsyncSessionLocal
    from app.models.chain_snapshot import ChainSnapshot

    out = {}
    async with AsyncSessionLocal() as session:
        for sym in SYMBOLS:
            row = (
                await session.execute(
                    select(
                        ChainSnapshot.underlying_price,
                        ChainSnapshot.timestamp,
                    )
                    .where(ChainSnapshot.symbol == sym)
                    .order_by(desc(ChainSnapshot.timestamp))
                    .limit(2)
                )
            ).scalars().all()
            if len(row) >= 1:
                price = float(row[0][0] or 0)
                change = 0.0
                if len(row) >= 2 and row[1][0]:
                    change = round(price - float(row[1][0]), 2)
                out[sym] = {"price": round(price, 2), "change": change}
    return out


@router.get("/signals")
async def get_pro_signals(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    Combined Pro signals: quick (10s) + swing (DB) + explanation.
    """
    result = {}
    for sym in SYMBOLS:
        quick = await run_pro_quick_signal(session, sym)
        swing = await get_pro_swing_signal(session, sym)

        q_sig = quick.get("quick_signal", "Wait")
        s_sig = swing or "Wait"

        result[sym] = {
            "quick_signal": q_sig,
            "swing_signal": s_sig,
            "explanation": explain_signal(q_sig, s_sig),
        }
    return result


@router.get("/commodities")
async def get_pro_commodities(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    Combined Pro commodity data: MCX prices + quick signal + long signal + explanation.
    Symbols: CRUDEOIL, NATGAS, GOLD, SILVER.
    """
    mcx = await get_mcx_prices()
    result: dict[str, Any] = {}

    for sym in COMMODITIES:
        tick_data = mcx.get(sym, {}) if isinstance(mcx, dict) and "error" not in mcx else {}
        quick_res = await commodity_quick_signal(session, sym)
        long_res = await commodity_long_term_signal(session, sym)

        q_sig = (quick_res.get("signal") or "WAIT").strip()
        l_sig = (long_res.get("signal") or "WAIT").strip()

        result[sym] = {
            "price": tick_data.get("price"),
            "change": tick_data.get("change"),
            "change_pct": tick_data.get("change_pct"),
            "quick_signal": q_sig,
            "long_signal": l_sig,
            "explanation": explain_commodity_signal(q_sig, l_sig),
        }
    return result
