"""
Commodity Collector — persists MCX commodity snapshots every 30 seconds.

Collects: CRUDEOIL, NATGAS, GOLD, SILVER (nearest futures via Zerodha quotes).
No changes to index ingestion; this runs independently.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.analytics.mcx_prices import get_mcx_prices
from app.db.database import AsyncSessionLocal
from app.logging_config import get_logger
from app.models.commodity_snapshot import CommoditySnapshot

logger = get_logger(__name__)

POLL_SECONDS = 30
SYMBOLS = ("CRUDEOIL", "NATGAS", "GOLD", "SILVER")


async def run_commodity_collector() -> None:
    """Background loop — persists commodity snapshots every 30s."""
    logger.info("Commodity collector started", interval=POLL_SECONDS, symbols=list(SYMBOLS))
    while True:
        try:
            data = await get_mcx_prices()
            if data.get("error"):
                logger.warning("Commodity collector: mcx-prices error", error=data["error"])
            else:
                ts = datetime.now(timezone.utc)
                async with AsyncSessionLocal() as session:
                    for sym in SYMBOLS:
                        row = data.get(sym) or {}
                        price = row.get("price")
                        if price is None:
                            continue
                        # Kite quote may include volume/oi in some accounts; default to 0.
                        vol = float(row.get("volume") or 0)
                        oi = float(row.get("oi") or 0)
                        session.add(
                            CommoditySnapshot(
                                symbol=sym,
                                price=float(price),
                                volume=vol,
                                oi=oi,
                                timestamp=ts,
                            )
                        )
                    await session.commit()
        except Exception as exc:
            logger.warning("Commodity collector cycle failed", error=str(exc))

        await asyncio.sleep(POLL_SECONDS)

