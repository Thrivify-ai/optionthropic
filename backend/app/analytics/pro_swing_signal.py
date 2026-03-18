"""
Pro Swing Signal — wrapper that reuses existing swing/long-term logic.

Reads from TradingSignalRow (existing table). Does not modify any existing code.
"""

from __future__ import annotations

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_signal import TradingSignalRow


async def get_pro_swing_signal(session: AsyncSession, symbol: str) -> str:
    """
    Return swing signal for symbol from existing DB.
    Maps: Buy CE -> Bullish, Buy PE -> Bearish, Wait -> Sideways.
    Returns: "Buy CE" | "Buy PE" | "Wait"
    """
    stmt = (
        select(TradingSignalRow.signal)
        .where(TradingSignalRow.symbol == symbol.upper())
        .order_by(desc(TradingSignalRow.generated_at))
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if not row:
        return "Wait"
    sig = (row[0] or "Wait").strip()
    if sig in ("Buy CE", "Buy PE", "Wait"):
        return sig
    if sig in ("BUY_CE", "buy_ce"):
        return "Buy CE"
    if sig in ("BUY_PE", "buy_pe"):
        return "Buy PE"
    return "Wait"
