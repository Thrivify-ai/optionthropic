"""
DB-backed service layer for critical global-news alerts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.global_news_scoring import NewsCandidate, parse_rss_items, score_news_candidate
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.logging_config import get_logger
from app.models.global_news_alert import GlobalNewsAlert
from app.services.market_hours import global_news_cache_ttl_seconds, global_news_poll_interval_seconds
from app.services.runtime_cache import runtime_cache

logger = get_logger(__name__)

GLOBAL_ALERTS_CACHE_KEY = "global-news:critical:v1"
GLOBAL_ALERTS_LAST_REFRESH_KEY = "global-news:critical:last-refresh"


async def _fetch_rss_candidates() -> list[NewsCandidate]:
    urls = [url for url in settings.global_news_rss_urls if url]
    if not urls:
        return []

    headers = {
        "User-Agent": "OptionthropicNewsBot/1.0 (+https://optionthropic.com)",
    }
    timeout = httpx.Timeout(settings.global_news_timeout_seconds)
    candidates: list[NewsCandidate] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for url in urls:
            try:
                response = await client.get(url)
                response.raise_for_status()
                candidates.extend(parse_rss_items(response.text))
            except Exception as exc:
                logger.warning("Global news feed fetch failed", url=url, error=str(exc))

    return candidates


def _serialize_alert_row(row: GlobalNewsAlert) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "source": row.source,
        "title": row.title,
        "summary": row.summary,
        "url": row.url,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "impact_score": row.impact_score,
        "move_potential": row.move_potential,
        "severity": row.severity,
        "affected_symbols": row.affected_symbols or [],
        "matched_themes": row.matched_themes or [],
        "impact_reason": row.impact_reason,
    }


async def _latest_alert_rows(session: AsyncSession, limit: int | None = None) -> list[GlobalNewsAlert]:
    limit_value = limit or settings.global_news_limit
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.global_news_lookback_hours)
    rows = (
        await session.execute(
            select(GlobalNewsAlert)
            .where(
                GlobalNewsAlert.is_critical.is_(True),
                GlobalNewsAlert.fetched_at >= cutoff,
            )
            .order_by(
                desc(GlobalNewsAlert.published_at),
                desc(GlobalNewsAlert.impact_score),
                desc(GlobalNewsAlert.fetched_at),
            )
            .limit(limit_value)
        )
    ).scalars().all()
    return list(rows)


async def _store_candidates(session: AsyncSession, candidates: list[NewsCandidate]) -> None:
    if not candidates:
        return

    lookback_cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.global_news_lookback_hours)
    existing_rows = (
        await session.execute(
            select(GlobalNewsAlert.dedupe_key).where(GlobalNewsAlert.fetched_at >= lookback_cutoff)
        )
    ).scalars().all()
    existing = set(existing_rows)
    now_utc = datetime.now(timezone.utc)

    for candidate in candidates:
        scored = score_news_candidate(candidate, now_utc=now_utc)
        if not scored["is_critical"] or scored["dedupe_key"] in existing:
            continue

        try:
            async with session.begin_nested():
                session.add(
                    GlobalNewsAlert(
                        provider=candidate.provider,
                        source=candidate.source[:200] if candidate.source else "Unknown",
                        title=candidate.title[:600],
                        summary=(candidate.summary or "")[:4000],
                        url=candidate.url,
                        published_at=candidate.published_at,
                        fetched_at=now_utc,
                        impact_score=scored["impact_score"],
                        move_potential=scored["move_potential"],
                        severity=scored["severity"],
                        affected_symbols=scored["affected_symbols"],
                        matched_themes=scored["matched_themes"],
                        impact_reason=scored["impact_reason"],
                        dedupe_key=scored["dedupe_key"],
                        is_critical=True,
                    )
                )
                await session.flush()
            existing.add(scored["dedupe_key"])
        except IntegrityError:
            logger.debug(
                "Global news duplicate skipped",
                title=candidate.title[:120],
                dedupe_key=scored["dedupe_key"],
            )


def _matches_requested_symbols(affected_symbols: list[str] | None, requested_symbols: set[str]) -> bool:
    if not requested_symbols:
        return True
    affected = {str(item).upper() for item in (affected_symbols or [])}
    return bool(affected & requested_symbols)


async def list_recent_global_news_alerts(
    session: AsyncSession,
    *,
    symbols: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    limit_value = limit or settings.global_news_limit
    requested_symbols = {str(symbol).upper() for symbol in (symbols or []) if symbol}
    rows = await _latest_alert_rows(session, limit=max(limit_value * 4, settings.global_news_limit * 3))
    filtered = [row for row in rows if _matches_requested_symbols(row.affected_symbols, requested_symbols)]
    return [_serialize_alert_row(row) for row in filtered[:limit_value]]


async def _cache_payload(payload: dict[str, Any], now_utc: datetime | None = None) -> None:
    await runtime_cache.set_json(
        GLOBAL_ALERTS_CACHE_KEY,
        payload,
        ttl_seconds=global_news_cache_ttl_seconds(now_utc),
    )


async def _set_last_refresh(now_utc: datetime) -> None:
    await runtime_cache.set_json(
        GLOBAL_ALERTS_LAST_REFRESH_KEY,
        {"refreshed_at": now_utc.isoformat()},
        ttl_seconds=global_news_cache_ttl_seconds(now_utc),
    )


async def _is_refresh_due(now_utc: datetime) -> bool:
    state = await runtime_cache.get_json(GLOBAL_ALERTS_LAST_REFRESH_KEY)
    if not isinstance(state, dict) or not state.get("refreshed_at"):
        return True
    try:
        last = datetime.fromisoformat(str(state["refreshed_at"]))
    except ValueError:
        return True
    return now_utc - last >= timedelta(seconds=global_news_poll_interval_seconds(now_utc))


async def refresh_global_news_alerts(force: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    if not settings.global_news_enabled:
        return {"alerts": [], "generated_at": now.isoformat(), "cached": True, "count": 0}

    if not force and not await _is_refresh_due(now):
        cached = await runtime_cache.get_json(GLOBAL_ALERTS_CACHE_KEY)
        if isinstance(cached, dict):
            return cached

    candidates = await _fetch_rss_candidates()
    async with AsyncSessionLocal() as session:
        try:
            await _store_candidates(session, candidates)
            rows = await _latest_alert_rows(session)
            payload = {
                "alerts": [_serialize_alert_row(row) for row in rows],
                "generated_at": now.isoformat(),
                "cached": False,
                "count": len(rows),
            }
            await session.commit()
            await _cache_payload(payload, now)
            await _set_last_refresh(now)
            return payload
        except Exception:
            await session.rollback()
            raise


async def get_global_news_alerts_payload(
    session: AsyncSession,
    *,
    limit: int | None = None,
    allow_stale: bool = True,
    refresh_if_missing: bool = False,
) -> dict[str, Any]:
    cached = await runtime_cache.get_json(GLOBAL_ALERTS_CACHE_KEY)
    if isinstance(cached, dict) and cached.get("alerts") is not None:
        return cached

    rows = await _latest_alert_rows(session, limit=limit)
    if rows:
        payload = {
            "alerts": [_serialize_alert_row(row) for row in rows],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cached": allow_stale,
            "count": len(rows),
        }
        await _cache_payload(payload)
        return payload

    if refresh_if_missing and settings.global_news_enabled:
        try:
            return await refresh_global_news_alerts(force=True)
        except Exception as exc:
            logger.warning("Global news refresh failed on demand", error=str(exc))

    return {
        "alerts": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": allow_stale,
        "count": 0,
    }


async def warm_global_news_alerts_cache() -> None:
    async with AsyncSessionLocal() as session:
        payload = await get_global_news_alerts_payload(
            session,
            allow_stale=True,
            refresh_if_missing=False,
        )
        await _cache_payload(payload)
