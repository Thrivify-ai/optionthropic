"""
Admin-only analytics endpoints.

All routes require is_admin=True on the authenticated user.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_routes import require_admin
from app.config import settings
from app.db.database import get_db
from app.models.alert import Alert
from app.models.buy_signal_history import BuySignalHistory
from app.models.chain_snapshot import ChainSnapshot
from app.models.options_snapshot import OptionsSnapshot
from app.models.user import User
from app.models.user_events import UserEvent

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── /admin/user-stats ─────────────────────────────────────────────────────────

@router.get("/user-stats")
async def user_stats(
    _: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    total = (await session.execute(select(func.count()).select_from(User))).scalar()
    active = (
        await session.execute(
            select(func.count()).select_from(User).where(User.is_active == True)
        )
    ).scalar()

    plan_rows = (
        await session.execute(
            select(User.plan, func.count().label("cnt"))
            .group_by(User.plan)
        )
    ).all()

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    new_week = (
        await session.execute(
            select(func.count()).select_from(User).where(User.created_at >= week_ago)
        )
    ).scalar()

    return {
        "total_users": total,
        "active_users": active,
        "new_last_7_days": new_week,
        "by_plan": {row.plan.value: row.cnt for row in plan_rows},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── /admin/usage-stats ────────────────────────────────────────────────────────

@router.get("/usage-stats")
async def usage_stats(
    _: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    events_today = (
        await session.execute(
            select(
                UserEvent.event_name,
                func.count().label("cnt"),
            )
            .where(UserEvent.timestamp >= day_ago)
            .group_by(UserEvent.event_name)
            .order_by(func.count().desc())
        )
    ).all()

    snapshots_today = (
        await session.execute(
            select(
                OptionsSnapshot.symbol,
                func.count().label("cnt"),
            )
            .where(OptionsSnapshot.timestamp >= day_ago)
            .group_by(OptionsSnapshot.symbol)
        )
    ).all()

    alerts_today = (
        await session.execute(
            select(func.count())
            .select_from(Alert)
            .where(Alert.timestamp >= day_ago)
        )
    ).scalar()

    return {
        "events_last_24h": {row.event_name: row.cnt for row in events_today},
        "snapshots_last_24h": {row.symbol: row.cnt for row in snapshots_today},
        "alerts_last_24h": alerts_today,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── /admin/system-health ─────────────────────────────────────────────────────

@router.get("/system-health")
async def system_health(
    _: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    import asyncio

    # DB ping
    db_ok = False
    db_latency_ms = None
    try:
        start = datetime.now(timezone.utc)
        await session.execute(text("SELECT 1"))
        db_latency_ms = round(
            (datetime.now(timezone.utc) - start).total_seconds() * 1000, 2
        )
        db_ok = True
    except Exception as exc:
        db_ok = False

    # Latest ingestion age
    latest_snap_ts = (
        await session.execute(
            select(func.max(OptionsSnapshot.timestamp))
        )
    ).scalar()
    ingestion_age_seconds = None
    if latest_snap_ts:
        ingestion_age_seconds = round(
            (datetime.now(timezone.utc) - latest_snap_ts).total_seconds(), 1
        )

    stale = (
        ingestion_age_seconds is None
        or ingestion_age_seconds > settings.poll_interval_seconds * 3
    )

    return {
        "status": "degraded" if (not db_ok or stale) else "healthy",
        "database": {
            "connected": db_ok,
            "latency_ms": db_latency_ms,
        },
        "data_ingestion": {
            "latest_snapshot_age_seconds": ingestion_age_seconds,
            "stale": stale,
            "poll_interval_seconds": settings.poll_interval_seconds,
        },
        "supported_symbols": settings.supported_symbols,
        "environment": settings.environment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── /admin/signal-analytics ────────────────────────────────────────────────────────

async def _price_at_time(session: AsyncSession, symbol: str, target: datetime) -> float | None:
    """Get underlying_price from ChainSnapshot closest to target (within 15 min)."""
    window = timedelta(minutes=15)
    stmt = (
        select(ChainSnapshot.underlying_price, ChainSnapshot.timestamp)
        .where(
            ChainSnapshot.symbol == symbol,
            ChainSnapshot.timestamp >= target - window,
            ChainSnapshot.timestamp <= target + window,
        )
        .order_by(ChainSnapshot.timestamp.desc())
        .limit(50)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None
    target_ts = target.timestamp()
    seen_ts = set()
    best_row = None
    best_diff = float("inf")
    for price, ts in rows:
        if ts in seen_ts:
            continue
        seen_ts.add(ts)
        diff = abs((ts or target).timestamp() - target_ts)
        if diff < best_diff:
            best_diff = diff
            best_row = price
    return float(best_row) if best_row is not None else None


def _outcome(signal: str, price_at: float, price_later: float | None) -> str:
    if not price_at or not price_later:
        return "Unknown"
    move = price_later - price_at
    if signal == "Buy CE" and move > 0:
        return "Won"
    if signal == "Buy CE" and move < 0:
        return "Lost"
    if signal == "Buy PE" and move < 0:
        return "Won"
    if signal == "Buy PE" and move > 0:
        return "Lost"
    return "Unknown"


@router.get("/signal-analytics")
async def signal_analytics(
    _: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
    limit: int = 200,
) -> Any:
    """
    Analyze buy signal history. Two sections:
    - Quick signals: 2m, 3m (short-term)
    - Long signals: 5m, 10m, 30m (long-term)
    Classify by reason: "Swing signal" -> long, else -> quick.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(BuySignalHistory)
        .where(BuySignalHistory.created_at >= cutoff)
        .order_by(desc(BuySignalHistory.created_at))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    rows = [r for r in rows if r.signal in ("Buy CE", "Buy PE")]

    quick_signals = []
    long_signals = []
    quick_won = quick_lost = quick_unknown = 0
    long_won = long_lost = long_unknown = 0

    for r in rows:
        t0 = r.created_at.replace(tzinfo=timezone.utc) if r.created_at.tzinfo is None else r.created_at
        price_at = float(r.level) if r.level is not None else None
        if price_at is None:
            price_at = await _price_at_time(session, r.symbol, t0)

        price_2m = await _price_at_time(session, r.symbol, t0 + timedelta(minutes=2))
        price_3m = await _price_at_time(session, r.symbol, t0 + timedelta(minutes=3))
        price_5m = await _price_at_time(session, r.symbol, t0 + timedelta(minutes=5))
        price_10m = await _price_at_time(session, r.symbol, t0 + timedelta(minutes=10))
        price_30m = await _price_at_time(session, r.symbol, t0 + timedelta(minutes=30))

        # Classify: "Swing signal" in reason -> long, else -> quick
        is_long = (r.reason or "").lower().find("swing") >= 0

        outcome_2m = _outcome(r.signal, price_at, price_2m)
        outcome_3m = _outcome(r.signal, price_at, price_3m)
        outcome_5m = _outcome(r.signal, price_at, price_5m)
        outcome_10m = _outcome(r.signal, price_at, price_10m)
        outcome_30m = _outcome(r.signal, price_at, price_30m)

        # Quick section: short-term outcomes (2m preferred, else 3m)
        outcome_short = outcome_2m if outcome_2m != "Unknown" else outcome_3m
        if not is_long:
            if outcome_short == "Won":
                quick_won += 1
            elif outcome_short == "Lost":
                quick_lost += 1
            else:
                quick_unknown += 1

        # Long section: long-term outcomes (5m preferred, else 10m, else 30m)
        outcome_long = outcome_5m if outcome_5m != "Unknown" else outcome_10m if outcome_10m != "Unknown" else outcome_30m
        if is_long:
            if outcome_long == "Won":
                long_won += 1
            elif outcome_long == "Lost":
                long_lost += 1
            else:
                long_unknown += 1

        base = {
            "id": r.id,
            "symbol": r.symbol,
            "signal": r.signal,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "price_at_signal": round(price_at, 2) if price_at is not None else None,
        }

        if not is_long:
            quick_signals.append({
                **base,
                "price_2m": round(price_2m, 2) if price_2m is not None else None,
                "price_3m": round(price_3m, 2) if price_3m is not None else None,
                "move_2m": round(price_2m - price_at, 2) if (price_at and price_2m) else None,
                "move_3m": round(price_3m - price_at, 2) if (price_at and price_3m) else None,
                "outcome_2m": outcome_2m,
                "outcome_3m": outcome_3m,
            })

        if is_long:
            long_signals.append({
                **base,
                "price_5m": round(price_5m, 2) if price_5m is not None else None,
                "price_10m": round(price_10m, 2) if price_10m is not None else None,
                "price_30m": round(price_30m, 2) if price_30m is not None else None,
                "move_5m": round(price_5m - price_at, 2) if (price_at and price_5m) else None,
                "move_10m": round(price_10m - price_at, 2) if (price_at and price_10m) else None,
                "move_30m": round(price_30m - price_at, 2) if (price_at and price_30m) else None,
                "outcome_5m": outcome_5m,
                "outcome_10m": outcome_10m,
                "outcome_30m": outcome_30m,
            })

    quick_total = quick_won + quick_lost + quick_unknown
    long_total = long_won + long_lost + long_unknown
    quick_win_rate = round(100 * quick_won / (quick_won + quick_lost), 1) if (quick_won + quick_lost) > 0 else None
    long_win_rate = round(100 * long_won / (long_won + long_lost), 1) if (long_won + long_lost) > 0 else None

    return {
        "quick_signals": quick_signals,
        "long_signals": long_signals,
        "quick_summary": {
            "total": quick_total,
            "won": quick_won,
            "lost": quick_lost,
            "unknown": quick_unknown,
            "win_rate_pct": quick_win_rate,
        },
        "long_summary": {
            "total": long_total,
            "won": long_won,
            "lost": long_lost,
            "unknown": long_unknown,
            "win_rate_pct": long_win_rate,
        },
        "days": days,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
