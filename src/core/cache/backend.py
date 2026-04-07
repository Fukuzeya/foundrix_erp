"""Redis-backed cache with simple get/set/delete and tenant-scoped keys.

Falls back gracefully when Redis is unavailable — cache misses are
treated as normal operation, never as errors that break the application.

Usage::

    from src.core.cache import cache

    # Simple key-value
    await cache.set("user:123", {"name": "John"}, ttl=300)
    data = await cache.get("user:123")

    # Tenant-scoped keys
    await cache.set("partners:list", data, ttl=60, tenant_id="acme")
    # actual key: "tenant:acme:partners:list"

    # Invalidation
    await cache.delete("user:123")
    await cache.delete_pattern("partners:*", tenant_id="acme")
"""

import json
import logging
from typing import Any

import redis.asyncio as redis

from src.core.config import settings

logger = logging.getLogger(__name__)


class CacheBackend:
    """Async Redis cache with graceful degradation."""

    def __init__(self) -> None:
        self._redis: redis.Redis | None = None

    async def connect(self) -> None:
        """Initialize the Redis connection pool."""
        try:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            await self._redis.ping()
            logger.info("Redis cache connected at %s", settings.REDIS_URL)
        except Exception:
            logger.warning("Redis unavailable — cache disabled", exc_info=True)
            self._redis = None

    async def disconnect(self) -> None:
        """Close the Redis connection pool."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    def _make_key(self, key: str, tenant_id: str | None = None) -> str:
        """Build a cache key, optionally scoped to a tenant."""
        if tenant_id:
            return f"tenant:{tenant_id}:{key}"
        return f"global:{key}"

    async def get(self, key: str, *, tenant_id: str | None = None) -> Any | None:
        """Get a value from cache. Returns None on miss or Redis unavailable."""
        if not self._redis:
            return None
        try:
            full_key = self._make_key(key, tenant_id)
            raw = await self._redis.get(full_key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.warning("Cache get failed for key=%s", key, exc_info=True)
            return None

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl: int = 300,
        tenant_id: str | None = None,
    ) -> None:
        """Set a value in cache with TTL in seconds."""
        if not self._redis:
            return
        try:
            full_key = self._make_key(key, tenant_id)
            await self._redis.set(full_key, json.dumps(value, default=str), ex=ttl)
        except Exception:
            logger.warning("Cache set failed for key=%s", key, exc_info=True)

    async def delete(self, key: str, *, tenant_id: str | None = None) -> None:
        """Delete a specific key from cache."""
        if not self._redis:
            return
        try:
            full_key = self._make_key(key, tenant_id)
            await self._redis.delete(full_key)
        except Exception:
            logger.warning("Cache delete failed for key=%s", key, exc_info=True)

    async def delete_pattern(self, pattern: str, *, tenant_id: str | None = None) -> int:
        """Delete all keys matching a pattern. Returns count of keys deleted."""
        if not self._redis:
            return 0
        try:
            full_pattern = self._make_key(pattern, tenant_id)
            count = 0
            async for key in self._redis.scan_iter(match=full_pattern, count=100):
                await self._redis.delete(key)
                count += 1
            return count
        except Exception:
            logger.warning("Cache delete_pattern failed for pattern=%s", pattern, exc_info=True)
            return 0

    @property
    def is_available(self) -> bool:
        """Check if Redis is currently connected."""
        return self._redis is not None


# Singleton cache instance
cache = CacheBackend()
