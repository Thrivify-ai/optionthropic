"""
Commodity insights backed by signals plus relevant critical global news.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.global_news import list_recent_global_news_alerts
from app.analytics.commodity_signals import commodity_long_term_signal, commodity_quick_signal
from app.models.commodity_snapshot import CommoditySnapshot
from app.services.market_hours import is_mcx_market_open

_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}
MARKET_OPEN_TTL_SECONDS = 15
MARKET_CLOSED_TTL_SECONDS = 900


def _cache_ttl_seconds() -> int:
    return MARKET_OPEN_TTL_SECONDS if is_mcx_market_open() else MARKET_CLOSED_TTL_SECONDS


async def _latest_price(session: AsyncSession, symbol: str) -> Optional[float]:
    row = (
        await session.execute(
            select(CommoditySnapshot.price)
            .where(CommoditySnapshot.symbol == symbol)
            .order_by(desc(CommoditySnapshot.timestamp))
            .limit(1)
        )
    ).scalars().first()
    return float(row) if row is not None else None


def _build_signal_insight(
    *,
    quick_signal: str,
    long_signal: str,
    quick_state: str,
    long_state: str,
    quick_setup_direction: str | None,
    long_setup_direction: str | None,
    quick_confidence: int,
    long_confidence: int,
) -> str:
    quick_direction = _commodity_direction(quick_signal)
    long_direction = _commodity_direction(long_signal)
    if _is_exit_signal(quick_signal) or _is_exit_signal(long_signal):
        exit_signal = quick_signal if _is_exit_signal(quick_signal) else long_signal
        return (
            f"{exit_signal} is active. The managed signal lifecycle is prioritizing risk reduction "
            "because follow-through or structure has weakened."
        )
    if _is_hold_signal(quick_signal) or _is_hold_signal(long_signal):
        hold_direction = quick_direction or long_direction or "the active direction"
        return (
            f"Managed {hold_direction} trade remains active. "
            "Hold while structure remains valid; use the displayed win/stop levels for risk control."
        )
    if quick_direction in ("LONG", "SHORT") and long_direction == quick_direction:
        return (
            f"Trend and momentum align ({quick_direction}). "
            f"Confidence LT {long_confidence}% and QS {quick_confidence}%. "
            "Prefer trading with the direction and managing risk on pullbacks."
        )
    if quick_direction in ("LONG", "SHORT") and long_signal == "WAIT":
        return (
            f"Short-term momentum suggests {quick_direction} (QS {quick_confidence}%) "
            "but the broader trend is not confirmed yet. Treat it as an intraday burst and stay strict on risk."
        )
    if long_state == "setup" and long_setup_direction in ("LONG", "SHORT") and quick_signal == "WAIT":
        return (
            f"Broader structure is building toward {long_setup_direction} (LT {long_confidence}%) "
            "but the 5-minute leg has not fully confirmed yet. Let momentum join before entering."
        )
    if quick_state == "setup" and quick_setup_direction in ("LONG", "SHORT") and long_signal == "WAIT":
        return (
            f"Quick momentum is forming toward {quick_setup_direction} (QS {quick_confidence}%), "
            "but it still needs one more confirmation before it becomes actionable."
        )
    if long_direction in ("LONG", "SHORT") and quick_signal == "WAIT":
        return (
            f"Long-term bias is {long_direction} (LT {long_confidence}%). "
            "Wait for quick momentum confirmation before entering."
        )
    return (
        f"Low-conviction state (LT {long_confidence}% and QS {quick_confidence}%). "
        "Avoid forcing trades and wait for a cleaner setup."
    )


def _commodity_direction(signal: str | None) -> str | None:
    normalized = str(signal or "").upper()
    if "LONG" in normalized:
        return "LONG"
    if "SHORT" in normalized:
        return "SHORT"
    return None


def _is_hold_signal(signal: str | None) -> bool:
    return str(signal or "").upper().startswith("HOLD ")


def _is_exit_signal(signal: str | None) -> bool:
    return str(signal or "").upper().startswith("EXIT ")


async def get_commodity_insights(session: AsyncSession, symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    now = datetime.now(timezone.utc)

    cached = _CACHE.get(symbol)
    if cached and (now - cached[0]).total_seconds() <= _cache_ttl_seconds():
        return cached[1]

    price = await _latest_price(session, symbol)
    quick = await commodity_quick_signal(session, symbol)
    long_ = await commodity_long_term_signal(session, symbol)
    news_alerts = await list_recent_global_news_alerts(session, symbols=[symbol], limit=2)
    top_news = news_alerts[0] if news_alerts else None

    quick_signal = quick.get("signal", "WAIT")
    long_signal = long_.get("signal", "WAIT")
    quick_state = quick.get("state", "idle")
    long_state = long_.get("state", "idle")
    quick_setup_direction = quick.get("setup_direction")
    long_setup_direction = long_.get("setup_direction")
    quick_confidence = int(quick.get("confidence") or 0)
    long_confidence = int(long_.get("confidence") or 0)
    news_score = int((top_news or {}).get("impact_score") or 0)
    news_title = (top_news or {}).get("title")
    news_reason = (top_news or {}).get("impact_reason") or (top_news or {}).get("summary")
    news_source = (top_news or {}).get("source")

    if price is None:
        payload = {
            "symbol": symbol,
            "insight": "No data yet for this commodity.",
            "news_alert": top_news,
            "news_impact_score": news_score,
            "timestamp": now.isoformat(),
        }
        _CACHE[symbol] = (now, payload)
        return payload

    insight = _build_signal_insight(
        quick_signal=quick_signal,
        long_signal=long_signal,
        quick_state=quick_state,
        long_state=long_state,
        quick_setup_direction=quick_setup_direction,
        long_setup_direction=long_setup_direction,
        quick_confidence=quick_confidence,
        long_confidence=long_confidence,
    )

    if top_news:
        insight = (
            f"{insight} News risk is active ({news_score}/100) from {news_source or 'a macro source'}: "
            f"{news_title}. {news_reason or 'Watch for volatility follow-through before sizing up.'}"
        )

    payload = {
        "symbol": symbol,
        "price": round(float(price), 2),
        "quick_signal": quick_signal,
        "quick_state": quick.get("state", "idle"),
        "quick_entry_ready": bool(quick.get("entry_ready", quick_signal != "WAIT")),
        "quick_setup_direction": quick.get("setup_direction"),
        "quick_confirmation_count": quick.get("confirmation_count"),
        "quick_required_confirmations": quick.get("required_confirmations"),
        "long_signal": long_signal,
        "long_state": long_.get("state", "idle"),
        "long_entry_ready": bool(long_.get("entry_ready", long_signal != "WAIT")),
        "long_setup_direction": long_.get("setup_direction"),
        "long_confirmation_count": long_.get("confirmation_count"),
        "long_required_confirmations": long_.get("required_confirmations"),
        "quick_confidence": quick_confidence,
        "long_confidence": long_confidence,
        "quick_reason": quick.get("reason"),
        "long_reason": long_.get("reason"),
        "quick_momentum_1m": quick.get("momentum_1m"),
        "quick_momentum_3m": quick.get("momentum_3m"),
        "quick_momentum_5m": quick.get("momentum_5m"),
        "long_pct_5m": long_.get("pct_5m"),
        "long_pct_30m": long_.get("pct_30m"),
        "long_pct_60m": long_.get("pct_60m"),
        "quick_volatility_ratio": quick.get("volatility_ratio"),
        "long_volatility_ratio": long_.get("volatility_ratio"),
        "quick_news_impact_score": quick.get("news_impact_score"),
        "long_news_impact_score": long_.get("news_impact_score"),
        "quick_trade": quick.get("trade"),
        "long_trade": long_.get("trade"),
        "quick_trade_state": quick.get("trade_state"),
        "long_trade_state": long_.get("trade_state"),
        "quick_current_points": quick.get("current_points"),
        "long_current_points": long_.get("current_points"),
        "quick_success_threshold_points": quick.get("success_threshold_points"),
        "long_success_threshold_points": long_.get("success_threshold_points"),
        "quick_stop_points": quick.get("stop_points"),
        "long_stop_points": long_.get("stop_points"),
        "news_alert": top_news,
        "news_title": news_title,
        "news_source": news_source,
        "news_reason": news_reason,
        "news_impact_score": news_score,
        "news_alerts": news_alerts,
        "insight": insight,
        "timestamp": now.isoformat(),
    }
    _CACHE[symbol] = (now, payload)
    return payload
