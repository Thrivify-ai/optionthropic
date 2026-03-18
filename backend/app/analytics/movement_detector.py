"""
Movement detector — checks whether there has been a meaningful move in the
underlying over the last 5 minutes and last 1 hour.

Used to decide when to refresh trade signals / AI insights instead of
blindly polling every 60 seconds.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chain_snapshot import ChainSnapshot
from app.logging_config import get_logger

logger = get_logger(__name__)


async def _latest_snapshot(session: AsyncSession, symbol: str) -> ChainSnapshot | None:
  stmt = (
    select(ChainSnapshot)
    .where(ChainSnapshot.symbol == symbol)
    .order_by(ChainSnapshot.timestamp.desc())
    .limit(1)
  )
  return (await session.execute(stmt)).scalars().first()


async def _snapshot_before(
  session: AsyncSession, symbol: str, cutoff: datetime
) -> ChainSnapshot | None:
  stmt = (
    select(ChainSnapshot)
    .where(
      ChainSnapshot.symbol == symbol,
      ChainSnapshot.timestamp <= cutoff,
    )
    .order_by(ChainSnapshot.timestamp.desc())
    .limit(1)
  )
  return (await session.execute(stmt)).scalars().first()


async def detect_movement(session: AsyncSession, symbol: str) -> dict[str, Any]:
  """
  Returns whether there is a meaningful move in the last 5m/1h.

  Heuristics:
  - 5m move > 0.35% or 25 points (whichever is larger)
  - 1h move > 0.8% or 60 points (whichever is larger)
  """
  now = datetime.now(timezone.utc)
  latest = await _latest_snapshot(session, symbol)
  if not latest:
    return {
      "symbol": symbol,
      "movement_significant": False,
      "reason": "no_data",
    }

  latest_price = float(latest.underlying_price or 0.0)
  if latest_price <= 0:
    return {
      "symbol": symbol,
      "movement_significant": False,
      "reason": "no_price",
    }

  five_ago = now - timedelta(minutes=5)
  hour_ago = now - timedelta(hours=1)

  snap_5m = await _snapshot_before(session, symbol, five_ago)
  snap_1h = await _snapshot_before(session, symbol, hour_ago)

  moved_5m = False
  moved_1h = False
  pct_5m = None
  pct_1h = None

  if snap_5m:
    p5 = float(snap_5m.underlying_price or 0.0)
    if p5 > 0:
      pct_5m = abs(latest_price - p5) / p5 * 100
      pts_5m = abs(latest_price - p5)
      thresh_pct_5 = 0.35
      thresh_pts_5 = 25.0
      moved_5m = pct_5m >= thresh_pct_5 or pts_5m >= thresh_pts_5

  if snap_1h:
    p1 = float(snap_1h.underlying_price or 0.0)
    if p1 > 0:
      pct_1h = abs(latest_price - p1) / p1 * 100
      pts_1h = abs(latest_price - p1)
      thresh_pct_1h = 0.8
      thresh_pts_1h = 60.0
      moved_1h = pct_1h >= thresh_pct_1h or pts_1h >= thresh_pts_1h

  movement = moved_5m or moved_1h

  return {
    "symbol": symbol,
    "movement_significant": bool(movement),
    "moved_5m": bool(moved_5m),
    "moved_1h": bool(moved_1h),
    "pct_5m": pct_5m,
    "pct_1h": pct_1h,
    "latest_price": latest_price,
    "latest_timestamp": latest.timestamp.isoformat(),
  }

