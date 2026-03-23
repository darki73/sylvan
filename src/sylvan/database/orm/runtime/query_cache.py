"""LRU query cache with TTL for frequently repeated single-record lookups."""

import threading
import time
from collections import OrderedDict
from typing import Any

from sylvan.logging import get_logger

logger = get_logger(__name__)

_MAX_CACHE_SIZE = 512
_DEFAULT_TTL = 30  # seconds


class QueryCache:
    """Thread-safe LRU cache with per-entry TTL.

    Entries expire after ``ttl`` seconds to prevent stale reads when
    external processes (CLI, other instances) modify the database.

    Attributes:
        _cache: The underlying LRU cache mapping key -> (value, timestamp).
        _hits: Number of cache hits.
        _misses: Number of cache misses.
    """

    def __init__(self, max_size: int = _MAX_CACHE_SIZE, ttl: int = _DEFAULT_TTL) -> None:
        """Initialize the query cache.

        Args:
            max_size: Maximum number of cached entries.
            ttl: Time-to-live in seconds for each entry.
        """
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[bool, Any]:
        """Look up a cached result.

        Returns a miss if the entry has expired.

        Args:
            key: Cache key (e.g., 'Symbol:path::Foo#function').

        Returns:
            Tuple of (found, value). If found is False, value is None.
        """
        with self._lock:
            if key in self._cache:
                value, ts = self._cache[key]
                if time.monotonic() - ts > self._ttl:
                    del self._cache[key]
                    self._misses += 1
                    return False, None
                self._hits += 1
                self._cache.move_to_end(key)
                return True, value
            self._misses += 1
            return False, None

    def put(self, key: str, value: Any) -> None:
        """Store a result in the cache with the current timestamp.

        Args:
            key: Cache key.
            value: The model instance to cache.
        """
        now = time.monotonic()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = (value, now)
            else:
                if len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
                self._cache[key] = (value, now)

    def invalidate(self, key: str) -> None:
        """Remove a specific entry from the cache.

        Args:
            key: Cache key to invalidate.
        """
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear the entire cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int | float]:
        """Return cache hit/miss statistics.

        Returns:
            Dict with 'hits', 'misses', 'size', and 'hit_rate' keys.
        """
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._cache),
                "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0.0,
            }


_instance: QueryCache | None = None
_instance_lock = threading.Lock()


def get_query_cache() -> QueryCache:
    """Get the global query cache instance.

    Returns:
        The singleton QueryCache instance.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = QueryCache()
    return _instance
