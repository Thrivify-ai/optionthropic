from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.runtime_cache import runtime_cache

_QUICK_SIGNAL_RESULT_TTL_SECONDS = 120


def _result_key(symbol: str) -> str:
    return f"quick-signal:latest:{symbol.upper()}:v3"


def _timestamp_now(now_utc: datetime | None = None) -> str:
    return (now_utc or datetime.now(timezone.utc)).isoformat()


def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def cache_quick_signal_payload(symbol: str, payload: dict[str, Any]) -> None:
    cached = dict(payload)
    cached["cached"] = False
    cached["cached_at"] = _timestamp_now()
    await runtime_cache.set_json(
        _result_key(symbol),
        cached,
        ttl_seconds=_QUICK_SIGNAL_RESULT_TTL_SECONDS,
    )


async def get_cached_quick_signal_payload(
    symbol: str,
    *,
    max_age_seconds: int = 30,
) -> dict[str, Any] | None:
    cached = await runtime_cache.get_json(_result_key(symbol))
    if not isinstance(cached, dict):
        return None
    timestamp = _parse_timestamp(cached.get("timestamp")) or _parse_timestamp(cached.get("cached_at"))
    if timestamp is None:
        return None
    age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
    if age_seconds > max_age_seconds:
        return None
    payload = dict(cached)
    payload["cached"] = True
    return payload
