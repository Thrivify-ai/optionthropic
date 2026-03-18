"""
Commodity AI insights — lightweight cached summaries.

We intentionally keep this fast and safe:
  - Pull latest price + quick + long-term signals
  - Generate a short insight string
  - Optionally (later) can be upgraded to use LLM like index insights
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.commodity_signals import commodity_quick_signal, commodity_long_term_signal
from app.models.commodity_snapshot import CommoditySnapshot
from sqlalchemy import select, desc


_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}
TTL_SECONDS = 60


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


async def get_commodity_insights(session: AsyncSession, symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    now = datetime.now(timezone.utc)

    cached = _CACHE.get(symbol)
    if cached and (now - cached[0]).total_seconds() <= TTL_SECONDS:
        return cached[1]

    price = await _latest_price(session, symbol)
    quick = await commodity_quick_signal(session, symbol)
    long_ = await commodity_long_term_signal(session, symbol)

    qsig = quick.get("signal", "WAIT")
    lsig = long_.get("signal", "WAIT")
    qconf = int(quick.get("confidence") or 0)
    lconf = int(long_.get("confidence") or 0)

    if price is None:
        out = {
            "symbol": symbol,
            "insight": "No data yet for this commodity.",
            "timestamp": now.isoformat(),
        }
        _CACHE[symbol] = (now, out)
        return out

    # Simple deterministic insight
    # Signals are already gated at >=70% confidence; still present confidence in narrative.
    if qsig in ("LONG", "SHORT") and lsig == qsig:
        insight = f"Trend and momentum align ({qsig}). Confidence LT {lconf}% · QS {qconf}%. Prefer trading with the direction; manage risk on pullbacks."
    elif qsig in ("LONG", "SHORT") and lsig == "WAIT":
        insight = f"Short-term momentum suggests {qsig} (QS {qconf}%) but long-term is not confirmed yet. Treat as an intraday burst; be quick and strict with risk."
    elif lsig in ("LONG", "SHORT") and qsig == "WAIT":
        insight = f"Long-term bias is {lsig} (LT {lconf}%). Wait for quick momentum confirmation before entry."
    else:
        insight = f"Low-conviction state (LT {lconf}% · QS {qconf}%). Avoid forcing trades; wait for a cleaner setup."

    out = {
        "symbol": symbol,
        "price": round(float(price), 2),
        "quick_signal": qsig,
        "long_signal": lsig,
        "quick_confidence": qconf,
        "long_confidence": lconf,
        "insight": insight,
        "timestamp": now.isoformat(),
    }
    _CACHE[symbol] = (now, out)
    return out

