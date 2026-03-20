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

from app.analytics.signal_outcomes import build_signal_analytics_payload
from app.api.auth_routes import require_admin
from app.config import settings
from app.db.database import get_db
from app.models.alert import Alert
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


@router.get("/signal-analytics")
async def signal_analytics(
    _: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
    limit: int = 200,
) -> Any:
    return await build_signal_analytics_payload(session, days=days, limit=limit)
