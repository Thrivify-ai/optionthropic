"""
Core analytics API routes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_engine.market_explainer import explain_market
from app.alerts.alert_engine import run_alert_evaluation
from app.alerts.global_news import get_global_news_alerts_payload, list_recent_global_news_alerts
from app.analytics.dashboard_cache import get_dashboard_overview
from app.analytics.dashboard_view_utils import serialize_trading_signal_payload
from app.analytics.gamma_detection import compute_gamma_walls
from app.analytics.liquidity_trap_detection import detect_liquidity_traps
from app.analytics.market_scanner import fetch_market_breadth_snapshot
from app.analytics.market_sandbox import list_sandbox_scenarios, run_market_sandbox
from app.analytics.max_pain_detection import compute_max_pain
from app.analytics.options_analysis import compute_pcr, compute_support_resistance
from app.analytics.options_flow_detection import detect_options_flow
from app.analytics.positioning_shift import detect_positioning_shifts
from app.analytics.quant_signal_capture import (
    build_quant_context,
    record_quant_signal_candidate,
)
from app.analytics.quick_signal_cache import get_cached_quick_signal_payload
from app.analytics.quick_signal_observer import capture_quick_quant_observation
from app.analytics.quick_signal import get_quick_signal
from app.analytics.quick_signal_engine import run_quick_signal_engine
from app.analytics.trade_manager import get_latest_trade_row, get_open_trade_row, serialize_trade_summary
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
from app.services.market_hours import get_equity_market_status, get_mcx_market_status
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

@router.get("/dashboard-overview")
async def get_dashboard_overview_route(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    return await get_dashboard_overview(session)


@router.get("/market-status")
async def get_market_status_route(
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    now = datetime.now(timezone.utc)
    equities = get_equity_market_status(now)
    mcx = get_mcx_market_status(now)
    return {
        "generated_at": now.isoformat(),
        "tracker_open": equities.is_open,
        "equities": {
            "is_open": equities.is_open,
            "session": equities.session,
            "is_holiday": equities.is_holiday,
            "reason": equities.reason,
            "next_open_ist": equities.next_open_ist,
        },
        "mcx": {
            "is_open": mcx.is_open,
            "session": mcx.session,
            "is_holiday": mcx.is_holiday,
            "reason": mcx.reason,
            "next_open_ist": mcx.next_open_ist,
        },
    }


@router.get("/scanners/index-breadth/{symbol}")
async def get_index_breadth_scanner(
    symbol: str,
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    symbol = _validate_symbol(symbol)
    snapshot = await fetch_market_breadth_snapshot(symbol)
    return {
        "symbol": snapshot.symbol,
        "universe_size": snapshot.universe_size,
        "advancers": snapshot.advancers,
        "decliners": snapshot.decliners,
        "unchanged": snapshot.unchanged,
        "avg_change_pct": snapshot.avg_change_pct,
        "breadth_score": snapshot.breadth_score,
        "leadership_score": snapshot.leadership_score,
        "direction_bias": snapshot.direction_bias,
        "aligned_bullish": snapshot.aligned_bullish,
        "aligned_bearish": snapshot.aligned_bearish,
        "available": snapshot.available,
        "reason": snapshot.reason,
        "fetched_at": snapshot.fetched_at,
    }


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


@router.get("/sandbox/scenarios")
async def get_sandbox_scenarios(
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    return {
        "scenarios": list_sandbox_scenarios(),
        "symbols": [
            "NIFTY",
            "BANKNIFTY",
            "SENSEX",
            "CRUDEOIL",
            "NATGAS",
            "GOLD",
            "SILVER",
        ],
    }


@router.get("/sandbox/run")
async def run_sandbox_validation(
    symbol: str = Query(default="NIFTY"),
    scenario: str = Query(default="trend_up_news"),
    steps: int = Query(default=120, ge=30, le=240),
    seed: int = Query(default=7, ge=1, le=9999),
    _: Annotated[User, Depends(get_current_user)] = None,
) -> Any:
    try:
        return run_market_sandbox(
            symbol=symbol,
            scenario_name=scenario,
            steps=steps,
            seed=seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        trade_row = await get_open_trade_row(session, engine="MAIN", symbol=symbol)
        if trade_row is None:
            trade_row = await get_latest_trade_row(session, engine="MAIN", symbol=symbol)
        payload = serialize_trading_signal_payload(None, serialize_trade_summary(trade_row))
        payload["symbol"] = symbol
        return payload

    trade_row = await get_open_trade_row(session, engine="MAIN", symbol=symbol)
    if trade_row is None:
        trade_row = await get_latest_trade_row(session, engine="MAIN", symbol=symbol)
    payload = serialize_trading_signal_payload(row, serialize_trade_summary(trade_row))
    payload["symbol"] = row.symbol
    return payload


# ─── Live Ticks (tick-by-tick when WebSocket connected) ──────────────────────

@router.get("/live-ticks")
async def get_live_ticks(
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    """
    Return latest tick-by-tick prices from Zerodha WebSocket when connected.
    Falls back to empty dict — frontend should use /market-prices when empty.
    """
    import asyncio
    from app.services.tick_stream import get_latest_ticks

    ticks = await asyncio.to_thread(get_latest_ticks)
    if isinstance(ticks, dict) and ticks:
        return ticks
    return {}


# ─── Market Prices (ticker) ──────────────────────────────────────────────────

@router.get("/market-prices")
async def get_market_prices(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Any:
    """
    Return the latest price + day change for each symbol.

    Base price = yesterday's close. Source priority:
    1. DB: last snapshot before today's 9:00 AM IST (best — our own close)
    2. Zerodha: ohlc.close from quote API when DB has no pre-market data
    """
    from datetime import timedelta as _td

    from app.analytics.index_quotes import fetch_index_quotes_from_zerodha

    _IST = _td(hours=5, minutes=30)
    now_utc      = datetime.now(timezone.utc)
    now_ist      = now_utc + _IST
    day_open_utc = (now_ist.replace(hour=9, minute=0, second=0, microsecond=0)) - _IST

    result: dict[str, Any] = {}
    symbols_missing_base: list[str] = []
    symbols_missing_all: list[str] = []

    for symbol in settings.supported_symbols:
        # ── Latest (current) price from DB ─────────────────────────────────
        latest_price_row = (
            await session.execute(
                select(ChainSnapshot.underlying_price)
                .where(ChainSnapshot.symbol == symbol)
                .order_by(desc(ChainSnapshot.timestamp))
                .limit(1)
            )
        ).scalars().first()

        # ── Previous-close base: last snapshot before today's open ──────────
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

        if current is not None and base is None:
            symbols_missing_base.append(symbol)
        elif current is None:
            symbols_missing_all.append(symbol)

        change     = round(current - base, 2)          if (current and base) else None
        change_pct = round(change / base * 100, 2)       if (change is not None and base) else None

        result[symbol] = {
            "price":      current,
            "change":     change,
            "change_pct": change_pct,
        }

    # ── Fetch from Zerodha when DB has no base (yesterday's close) or no data at all ───
    need_zerodha = symbols_missing_base or symbols_missing_all
    if need_zerodha:
        zerodha_quotes = await fetch_index_quotes_from_zerodha()
        for symbol in symbols_missing_base:
            zq = zerodha_quotes.get(symbol, {})
            z_prev = zq.get("prev_close")
            z_change = zq.get("change")
            z_pct = zq.get("change_pct")
            price = result[symbol].get("price")
            if z_prev is not None and price is not None:
                result[symbol]["change"] = z_change or round(price - z_prev, 2)
                result[symbol]["change_pct"] = z_pct or round(
                    result[symbol]["change"] / z_prev * 100, 2
                )
        for symbol in symbols_missing_all:
            zq = zerodha_quotes.get(symbol, {})
            if zq.get("price") is not None:
                result[symbol]["price"] = zq["price"]
                result[symbol]["change"] = zq.get("change")
                result[symbol]["change_pct"] = zq.get("change_pct")

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
    cached = await get_cached_quick_signal_payload(
        symbol,
        max_age_seconds=max(8, settings.quick_signal_poll_seconds),
    )
    if cached is not None:
        return cached

    payload = await run_quick_signal_engine(session, symbol)
    try:
        await capture_quick_quant_observation(session, symbol=symbol, payload=payload)
    except Exception as exc:
        logger.debug("quick_quant_capture_failed", symbol=symbol, error=str(exc))
    return payload


# ─── Buy Signal History (persisted for analytics) ──────────────────────────────

from pydantic import BaseModel as _PydanticBase

class BuySignalCreate(_PydanticBase):
    symbol: str
    signal: str  # "Buy CE" | "Buy PE"
    level: float | None = None
    momentum: float | None = None
    reason: str | None = None
    confidence: int | None = None
    engine: str | None = "QUICK"
    payload: dict[str, Any] | None = None


@router.post("/buy-signal-history")
async def create_buy_signal(
    body: BuySignalCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Any:
    """Persist a buy signal for analytics (called when Quick Signal fires Buy CE/PE).
    Deduplicates: same user+symbol+signal within 90s returns existing row."""
    from app.models.buy_signal_history import BuySignalHistory

    if body.signal not in ("Buy CE", "Buy PE"):
        raise HTTPException(status_code=400, detail="signal must be Buy CE or Buy PE")
    symbol = _validate_symbol(body.symbol)

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(seconds=90)
    dup = (
        select(BuySignalHistory)
        .where(
            BuySignalHistory.user_id == current_user.id,
            BuySignalHistory.symbol == symbol,
            BuySignalHistory.signal == body.signal,
            BuySignalHistory.created_at >= cutoff,
        )
        .order_by(desc(BuySignalHistory.created_at))
        .limit(1)
    )
    existing = (await session.execute(dup)).scalars().first()
    if existing:
        return {"id": existing.id, "symbol": symbol, "signal": body.signal, "created_at": existing.created_at.isoformat()}

    row = BuySignalHistory(
        user_id=current_user.id,
        symbol=symbol,
        signal=body.signal,
        level=body.level,
        momentum=body.momentum,
        reason=body.reason,
    )
    session.add(row)
    await session.flush()

    entry_price = float(body.level) if body.level is not None else None
    if entry_price is not None:
        from app.analytics.signal_outcomes import record_signal_outcome_candidate

        await record_signal_outcome_candidate(
            session,
            engine=(body.engine or "QUICK"),
            symbol=symbol,
            signal=body.signal,
            confidence=int(body.confidence or 0),
            entry_price=entry_price,
            entry_time=now_utc,
            reason=body.reason,
            state="active",
        )
        payload = body.payload or {}
        try:
            context = await build_quant_context(
                session,
                symbol=symbol,
                engine=(body.engine or "QUICK"),
                signal=body.signal,
                entry_time=now_utc,
                current_price=entry_price,
                support=float(payload["support"]) if payload.get("support") is not None else None,
                resistance=float(payload["resistance"]) if payload.get("resistance") is not None else None,
                momentum=float(body.momentum) if body.momentum is not None else float(payload["momentum"]) if payload.get("momentum") is not None else None,
                breakout=bool(payload.get("breakout")),
                breakdown=bool(payload.get("breakdown")),
                trap_detected=bool(payload.get("trap_detected")),
                rangebound=bool(payload.get("rangebound")),
                call_oi_delta=float(payload["call_oi_delta"]) if payload.get("call_oi_delta") is not None else None,
                put_oi_delta=float(payload["put_oi_delta"]) if payload.get("put_oi_delta") is not None else None,
                volume_spike=bool(payload.get("volume_spike")),
                writer_support=bool(payload.get("oi_confirmed")),
                outlook=str(payload.get("outlook")) if payload.get("outlook") is not None else None,
                state=str(payload.get("state")) if payload.get("state") is not None else "active",
                entry_ready=True,
            )
            await record_quant_signal_candidate(
                session,
                engine=(body.engine or "QUICK"),
                signal_version="quick_v4_live" if (body.engine or "QUICK").upper() == "QUICK" else "main_v4_live",
                symbol=symbol,
                signal=body.signal,
                confidence=int(body.confidence or 0),
                entry_time=now_utc,
                underlying_entry_price=entry_price,
                reason=body.reason,
                context=context,
                outlook=str(payload.get("outlook")) if payload.get("outlook") is not None else None,
                state=str(payload.get("state")) if payload.get("state") is not None else "active",
                entry_ready=True,
            )
        except Exception as exc:
            logger.debug("buy_signal_quant_capture_failed", symbol=symbol, error=str(exc))

    return {"id": row.id, "symbol": symbol, "signal": body.signal, "created_at": row.created_at.isoformat()}


@router.get("/buy-signal-history")
async def list_buy_signals(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    symbol: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    today_only: bool = Query(default=True, description="Return only today's IST signals"),
) -> Any:
    """List recent buy signals for the current user (for Quick Signals buy history)."""
    from app.models.buy_signal_history import BuySignalHistory

    stmt = (
        select(BuySignalHistory)
        .where(BuySignalHistory.user_id == current_user.id)
        .order_by(desc(BuySignalHistory.created_at))
        .limit(limit)
    )
    if symbol:
        stmt = stmt.where(BuySignalHistory.symbol == _validate_symbol(symbol))
    if today_only:
        stmt = stmt.where(
            func.date(func.timezone("Asia/Calcutta", BuySignalHistory.created_at))
            == func.date(func.timezone("Asia/Calcutta", func.now()))
        )
    rows = (await session.execute(stmt)).scalars().all()

    def _to_ist(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=5, minutes=30)))

    def _serialize_history_row(r: Any) -> dict[str, Any]:
        created_ist = _to_ist(r.created_at)
        return {
            "id": r.id,
            "symbol": r.symbol,
            "signal": r.signal,
            "level": float(r.level) if r.level else None,
            "momentum": float(r.momentum) if r.momentum else None,
            "reason": r.reason,
            "time": created_ist.strftime("%H:%M:%S") if created_ist else None,
            "date": created_ist.strftime("%Y-%m-%d") if created_ist else None,
            "datetime_ist": created_ist.strftime("%Y-%m-%d %H:%M:%S IST") if created_ist else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }

    return {
        "history": [_serialize_history_row(r) for r in rows],
        "today_only": today_only,
    }


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


@router.get("/global-news-alerts")
async def get_global_news_alerts_route(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    symbols: str | None = Query(default=None, description="Optional comma-separated symbols filter"),
    limit: int = Query(default=10, ge=1, le=25),
) -> Any:
    requested_symbols = [item.strip().upper() for item in (symbols or "").split(",") if item.strip()]
    if requested_symbols:
        alerts = await list_recent_global_news_alerts(session, symbols=requested_symbols, limit=limit)
        return {
            "alerts": alerts,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cached": True,
            "count": len(alerts),
        }

    return await get_global_news_alerts_payload(
        session,
        limit=limit,
        allow_stale=True,
        refresh_if_missing=True,
    )


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
