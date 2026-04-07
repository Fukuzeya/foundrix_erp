"""Cache layer abstraction with Redis backend."""

from src.core.cache.backend import CacheBackend, cache

__all__ = ["CacheBackend", "cache"]
