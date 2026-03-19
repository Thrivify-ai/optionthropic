"""
Shared runtime cache with optional Redis backing.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

try:
    from redis.asyncio import Redis
except Exception:  # pragma: no cover - optional dependency at runtime
    Redis = None  # type: ignore[assignment]


class RuntimeCache:
    def __init__(self) -> None:
        self._redis: Redis | None = None
        self._memory: dict[str, tuple[float | None, Any]] = {}

    async def start(self) -> None:
        if not settings.redis_url or Redis is None:
            if settings.redis_url and Redis is None:
                logger.warning("Redis URL configured but redis package unavailable; using in-memory cache")
            return

        try:
            client = Redis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            self._redis = client
            logger.info("Connected to Redis shared cache", redis_url=settings.redis_url)
        except Exception as exc:
            self._redis = None
            logger.warning("Redis unavailable; falling back to in-memory cache", error=str(exc))

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def get_json(self, key: str) -> Any | None:
        if self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw is None:
                    return None
                return json.loads(raw)
            except Exception as exc:
                logger.warning("Redis read failed; falling back to in-memory cache", key=key, error=str(exc))

        entry = self._memory.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and time.monotonic() >= expires_at:
            self._memory.pop(key, None)
            return None
        return value

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if self._redis is not None:
            try:
                raw = json.dumps(value, default=str)
                if ttl_seconds:
                    await self._redis.set(key, raw, ex=int(ttl_seconds))
                else:
                    await self._redis.set(key, raw)
                return
            except Exception as exc:
                logger.warning("Redis write failed; falling back to in-memory cache", key=key, error=str(exc))

        expires_at = time.monotonic() + ttl_seconds if ttl_seconds else None
        self._memory[key] = (expires_at, value)

    async def delete(self, key: str) -> None:
        if self._redis is not None:
            try:
                await self._redis.delete(key)
            except Exception as exc:
                logger.warning("Redis delete failed", key=key, error=str(exc))
        self._memory.pop(key, None)


runtime_cache = RuntimeCache()
