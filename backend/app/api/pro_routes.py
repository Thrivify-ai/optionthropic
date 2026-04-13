"""
Pro Signals API — live ticks, quick signals, swing signals, explanations.

New routes only. Does not modify existing APIs.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.global_news import get_global_news_alerts_payload
from app.analytics.commodity_insights import get_commodity_insights
from app.analytics.explanation_engine import explain_signal
from app.analytics.mcx_prices import get_mcx_prices
from app.analytics.quick_signal_cache import get_cached_quick_signal_payload
from app.analytics.quick_signal_engine import run_quick_signal_engine
from app.analytics.pro_swing_signal import get_pro_swing_signal
from app.api.auth_routes import require_pro
from app.config import settings
from app.db.database import get_db
from app.models.user import User
from app.services.tick_stream import get_latest_ticks

router = APIRouter(prefix="/api/pro", tags=["pro"])

SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"]
COMMODITIES = ["CRUDEOIL", "NATGAS", "GOLD", "SILVER"]


@router.get("/ticks")
async def get_pro_ticks(
    _: Annotated[User, Depends(require_pro)],
) -> dict[str, Any]:
    """
    Live tick data for NIFTY, BANKNIFTY, SENSEX.
    From WebSocket when available, else quote/DB fallback.
    """
    ticks = get_latest_ticks()
    if ticks:
        return {sym: {"price": d["price"], "change": d["change"]} for sym, d in ticks.items()}

    # Fallback: fetch from DB + Zerodha for yesterday's close when needed
    from sqlalchemy import select, desc
    from app.db.database import AsyncSessionLocal
    from app.models.chain_snapshot import ChainSnapshot
    from app.analytics.index_quotes import fetch_index_quotes_from_zerodha

    zerodha_quotes = await fetch_index_quotes_from_zerodha()
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
                    .limit(1)
                )
            ).first()
            if row is not None:
                price = float(row[0] or 0)
                change = 0.0
                zq = zerodha_quotes.get(sym, {})
                if zq.get("prev_close") is not None:
                    change = round(price - zq["prev_close"], 2)
                out[sym] = {"price": round(price, 2), "change": change}
    return out


@router.get("/signals")
async def get_pro_signals(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_pro)],
) -> dict[str, Any]:
    """
    Combined Pro signals: quick (live quick engine) + swing (DB) + explanation.
    """
    result = {}
    for sym in SYMBOLS:
        quick = await get_cached_quick_signal_payload(
            sym,
            max_age_seconds=max(8, settings.quick_signal_poll_seconds),
        )
        if quick is None:
            quick = await run_quick_signal_engine(session, sym)
        swing = await get_pro_swing_signal(session, sym)

        q_sig = quick.get("quick_signal", "Wait")
        s_sig = swing or "Wait"

        result[sym] = {
            "quick_signal": q_sig,
            "quick_payload": quick,
            "swing_signal": s_sig,
            "explanation": explain_signal(q_sig, s_sig),
        }
    return result


@router.get("/global-alerts")
async def get_pro_global_alerts(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_pro)],
) -> dict[str, Any]:
    """
    Curated world-news alerts filtered to only potentially market-moving items.
    """
    return await get_global_news_alerts_payload(
        session,
        allow_stale=True,
        refresh_if_missing=True,
    )


@router.get("/commodities")
async def get_pro_commodities(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_pro)],
) -> dict[str, Any]:
    """
    Combined Pro commodity data: MCX prices + quick signal + long signal + explanation.
    Symbols: CRUDEOIL, NATGAS, GOLD, SILVER.
    """
    mcx = await get_mcx_prices()
    result: dict[str, Any] = {}

    for sym in COMMODITIES:
        tick_data = mcx.get(sym, {}) if isinstance(mcx, dict) and "error" not in mcx else {}
        insight = await get_commodity_insights(session, sym)

        result[sym] = {
            "price": tick_data.get("price"),
            "change": tick_data.get("change"),
            "change_pct": tick_data.get("change_pct"),
            "quick_signal": insight.get("quick_signal", "WAIT"),
            "quick_state": insight.get("quick_state", "idle"),
            "quick_entry_ready": insight.get("quick_entry_ready", False),
            "quick_setup_direction": insight.get("quick_setup_direction"),
            "quick_confirmation_count": insight.get("quick_confirmation_count"),
            "quick_required_confirmations": insight.get("quick_required_confirmations"),
            "long_signal": insight.get("long_signal", "WAIT"),
            "long_state": insight.get("long_state", "idle"),
            "long_entry_ready": insight.get("long_entry_ready", False),
            "long_setup_direction": insight.get("long_setup_direction"),
            "long_confirmation_count": insight.get("long_confirmation_count"),
            "long_required_confirmations": insight.get("long_required_confirmations"),
            "quick_confidence": insight.get("quick_confidence"),
            "long_confidence": insight.get("long_confidence"),
            "quick_reason": insight.get("quick_reason"),
            "long_reason": insight.get("long_reason"),
            "quick_volatility_ratio": insight.get("quick_volatility_ratio"),
            "long_volatility_ratio": insight.get("long_volatility_ratio"),
            "quick_trade": insight.get("quick_trade"),
            "long_trade": insight.get("long_trade"),
            "quick_trade_state": insight.get("quick_trade_state"),
            "long_trade_state": insight.get("long_trade_state"),
            "quick_current_points": insight.get("quick_current_points"),
            "long_current_points": insight.get("long_current_points"),
            "quick_success_threshold_points": insight.get("quick_success_threshold_points"),
            "long_success_threshold_points": insight.get("long_success_threshold_points"),
            "quick_stop_points": insight.get("quick_stop_points"),
            "long_stop_points": insight.get("long_stop_points"),
            "news_alert": insight.get("news_alert"),
            "news_title": insight.get("news_title"),
            "news_source": insight.get("news_source"),
            "news_reason": insight.get("news_reason"),
            "news_impact_score": insight.get("news_impact_score"),
            "news_alerts": insight.get("news_alerts"),
            "explanation": insight.get("insight"),
        }
    return result
