"""
Core analytics API routes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_engine.market_explainer import explain_market
from app.alerts.alert_engine import run_alert_evaluation
from app.analytics.gamma_detection import compute_gamma_walls
from app.analytics.liquidity_trap_detection import detect_liquidity_traps
from app.analytics.max_pain_detection import compute_max_pain
from app.analytics.options_analysis import compute_pcr, compute_support_resistance
from app.analytics.options_flow_detection import detect_options_flow
from app.analytics.positioning_shift import detect_positioning_shifts
from app.analytics.quick_signal import get_quick_signal
from app.analytics.quick_signal_engine import run_quick_signal_engine
from app.analytics.mcx_prices import get_mcx_prices
from app.analytics.commodity_signals import commodity_quick_signal, commodity_long_term_signal
from app.analytics.commodity_insights import get_commodity_insights
from app.analytics.time_factor import get_time_factor_signal
from app.analytics.movement_detector import detect_movement
from app.api.auth_routes import get_current_user
from app.config import settings
from app.db.database import get_db
from app.logging_config import get_logger
from app.models.alert import Alert
from app.models.chain_snapshot import ChainSnapshot
from app.models.user import User
from app.models.trading_signal import TradingSignalRow
from sqlalchemy import select, desc, func

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["analytics"])


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol not in settings.supported_symbols:
        raise HTTPException(
            status_code=400,
            detail=f"Symbol must be one of: {settings.supported_symbols}",
        )
    return symbol


# ─── Options Chain ────────────────────────────────────────────────────────────

@router.get("/options-chain/{symbol}")
async def get_options_chain(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)

    pcr = await compute_pcr(session, symbol)
    sr = await compute_support_resistance(session, symbol)

    return {
        "symbol": symbol,
        "pcr": pcr,
        "support_resistance": sr,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Support / Resistance ─────────────────────────────────────────────────────

@router.get("/support-resistance/{symbol}")
async def get_support_resistance(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)
    return await compute_support_resistance(session, symbol)


# ─── Gamma Walls ──────────────────────────────────────────────────────────────

@router.get("/gamma-walls/{symbol}")
async def get_gamma_walls(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)
    result = await compute_gamma_walls(session, symbol)

    # Also persist to gamma_levels table
    from app.models.gamma_levels import GammaLevel

    if result.get("call_wall") and result.get("put_wall"):
        session.add(
            GammaLevel(
                symbol=symbol,
                support_strike=result.get("support_strike") or result["put_wall"],
                resistance_strike=result.get("resistance_strike") or result["call_wall"],
                call_wall=result["call_wall"],
                put_wall=result["put_wall"],
                timestamp=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    return result


# ─── Max Pain ─────────────────────────────────────────────────────────────────

@router.get("/max-pain/{symbol}")
async def get_max_pain(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)
    result = await compute_max_pain(session, symbol)

    # Persist latest max pain
    from app.models.max_pain_levels import MaxPainLevel
    from datetime import date

    if result.get("max_pain_strike"):
        session.add(
            MaxPainLevel(
                symbol=symbol,
                expiry=date.today(),
                max_pain_strike=result["max_pain_strike"],
                timestamp=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    return result


# ─── Options Flow ─────────────────────────────────────────────────────────────

@router.get("/options-flow/{symbol}")
async def get_options_flow(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    top_n: int = Query(default=20, ge=1, le=50),
) -> Any:
    symbol = _validate_symbol(symbol)
    return await detect_options_flow(session, symbol, top_n=top_n)


# ─── Positioning Shifts ───────────────────────────────────────────────────────

@router.get("/positioning-shifts/{symbol}")
async def get_positioning_shifts(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)
    return await detect_positioning_shifts(session, symbol)


# ─── Liquidity Traps ──────────────────────────────────────────────────────────

@router.get("/liquidity-traps/{symbol}")
async def get_liquidity_traps(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)
    return await detect_liquidity_traps(session, symbol)


# ─── Time factor (intraday key windows) ────────────────────────────────────────

@router.get("/time-factor")
async def get_time_factor(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(default="NIFTY", description="Symbol for bias (NIFTY, BANKNIFTY, SENSEX)"),
) -> Any:
    """Current IST time, key intraday window (10:30–10:55, 12:30, 1:20, 2:55 PM), and options-derived bias."""
    symbol = _validate_symbol(symbol)
    return await get_time_factor_signal(session, symbol)


# ─── Movement detector ────────────────────────────────────────────────────────

@router.get("/movement/{symbol}")
async def get_movement(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    """Return whether there has been a meaningful move in the underlying over the last 5m/1h."""
    symbol = _validate_symbol(symbol)
    return await detect_movement(session, symbol)


# ─── Trading signal (multi-timeframe) ────────────────────────────────────────

@router.get("/trading-signal/{symbol}")
async def get_trading_signal(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Return the latest generated trading signal for the symbol."""
    symbol = _validate_symbol(symbol)

    stmt = (
        select(TradingSignalRow)
        .where(TradingSignalRow.symbol == symbol)
        .order_by(desc(TradingSignalRow.generated_at))
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if not row:
        return {
            "symbol": symbol,
            "signal": "Wait",
            "confidence": 0,
            "support": None,
            "resistance": None,
            "bias_5m": "Neutral",
            "bias_30m": "Neutral",
            "bias_60m": "Neutral",
            "reason": "No signal generated yet.",
        }

    return {
        "symbol": row.symbol,
        "signal": row.signal,
        "confidence": row.confidence,
        "support": float(row.support) if row.support is not None else None,
        "resistance": float(row.resistance) if row.resistance is not None else None,
        "bias_5m": row.bias_5m,
        "bias_30m": row.bias_30m,
        "bias_60m": row.bias_60m,
        "reason": row.reason,
    }


# ─── Market Prices (ticker) ──────────────────────────────────────────────────

@router.get("/market-prices")
async def get_market_prices(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    """
    Return the latest price + day change for each symbol.

    Base price = last snapshot captured BEFORE today's 9:00 AM IST open.
    This is the previous trading session's closing price — the same baseline
    Zerodha and every other platform uses for the day-change percentage.

    Using today's first snapshot as the base would give a misleading "intraday
    drift from open" rather than the true day change vs yesterday's close.
    """
    from datetime import timedelta as _td

    _IST = _td(hours=5, minutes=30)
    now_utc      = datetime.now(timezone.utc)
    now_ist      = now_utc + _IST
    # Today's 9:00 AM IST in UTC
    day_open_utc = (now_ist.replace(hour=9, minute=0, second=0, microsecond=0)) - _IST

    result: dict[str, Any] = {}
    for symbol in settings.supported_symbols:
        # ── Latest (current) price ────────────────────────────────────────
        latest_price_row = (
            await session.execute(
                select(ChainSnapshot.underlying_price)
                .where(ChainSnapshot.symbol == symbol)
                .order_by(desc(ChainSnapshot.timestamp))
                .limit(1)
            )
        ).scalars().first()

        # ── Previous-close base price ─────────────────────────────────────
        # Always use the LAST snapshot from before today's open.
        # That is the most recent price captured while the market was closed
        # (i.e. end of yesterday's session), which matches Zerodha's reference.
        base_price_row = (
            await session.execute(
                select(ChainSnapshot.underlying_price)
                .where(
                    ChainSnapshot.symbol == symbol,
                    ChainSnapshot.timestamp < day_open_utc,
                )
                .order_by(desc(ChainSnapshot.timestamp))
                .limit(1)
            )
        ).scalars().first()

        current = float(latest_price_row) if latest_price_row is not None else None
        base    = float(base_price_row)   if base_price_row   is not None else None

        change     = round(current - base, 2)          if (current and base) else None
        change_pct = round(change / base * 100, 2)     if (change is not None and base) else None

        result[symbol] = {
            "price":      current,
            "change":     change,
            "change_pct": change_pct,
        }
    return result


# ─── MCX Prices (Crude Oil, Natural Gas) ──────────────────────────────────────

@router.get("/mcx-prices")
async def get_mcx_prices_route(
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    """
    Lightweight MCX ticker for CRUDEOIL and NATGAS (nearest futures).
    Uses Zerodha Kite quotes; no DB writes.
    """
    return await get_mcx_prices()


# ─── Commodity Signals (futures-based) ────────────────────────────────────────

@router.get("/commodity/quick-signal/{symbol}")
async def get_commodity_quick_signal(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = symbol.upper()
    return await commodity_quick_signal(session, symbol)


@router.get("/commodity/long-signal/{symbol}")
async def get_commodity_long_signal(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = symbol.upper()
    return await commodity_long_term_signal(session, symbol)


@router.get("/commodity/insights/{symbol}")
async def get_commodity_ai_insights(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = symbol.upper()
    return await get_commodity_insights(session, symbol)


# ─── Quick Signal (10-minute OI buildup) ─────────────────────────────────────

@router.get("/quick-signal/{symbol}")
async def get_quick_signal_route(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    """
    10-minute OI buildup quick signal.
    Detects put/call writing, buying, and unwinding at key strikes and
    returns a directional quick signal: Buy CE, Buy PE, Watch, or Wait.
    """
    symbol = _validate_symbol(symbol)
    return await get_quick_signal(session, symbol)


# ─── Quick Signal Engine (momentum + breakout + OI, independent engine) ───────

@router.get("/quick-signal-engine/{symbol}")
async def get_quick_signal_engine_route(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    """
    High-speed 6-step signal engine: momentum · volume spike · breakout ·
    OI confirmation · liquidity trap filter → Buy CE / Buy PE / Wait.
    Independent of all other signal engines and APIs.
    """
    symbol = _validate_symbol(symbol)
    return await run_quick_signal_engine(session, symbol)


# ─── Alerts ───────────────────────────────────────────────────────────────────

@router.get("/alerts/{symbol}")
async def get_alerts(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    symbol = _validate_symbol(symbol)
    stmt = (
        select(Alert)
        .where(Alert.symbol == symbol)
        .order_by(desc(Alert.timestamp))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "symbol": symbol,
        "alerts": [
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "description": a.description,
                "severity": a.severity,
                "timestamp": a.timestamp.isoformat(),
            }
            for a in rows
        ],
        "count": len(rows),
    }


# ─── AI Market Summary ────────────────────────────────────────────────────────

@router.get("/market-summary/{symbol}")
async def get_market_summary(
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)
    return await explain_market(session, symbol)


# ─── Trigger alert evaluation (internal use / webhook) ────────────────────────

@router.post("/alerts/{symbol}/evaluate")
async def trigger_alert_evaluation(
    symbol: str,
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)
    alerts = await run_alert_evaluation(symbol)
    return {"symbol": symbol, "alerts_fired": len(alerts), "alerts": alerts}
