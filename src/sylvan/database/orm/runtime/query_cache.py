"""LRU query cache for frequently repeated single-record lookups."""

import threading
from collections import OrderedDict
from typing import Any

from sylvan.logging import get_logger

logger = get_logger(__name__)

_MAX_CACHE_SIZE = 512


class QueryCache:
    """Thread-safe LRU cache for ORM single-record lookups.

    Caches results of find-by-unique-key queries to avoid repeated
    SQLite round-trips for the same record within a session.
    Uses ``OrderedDict`` with ``move_to_end`` for true LRU eviction.

    Attributes:
        _cache: The underlying LRU cache ordered dict.
        _hits: Number of cache hits.
        _misses: Number of cache misses.
    """

    def __init__(self, max_size: int = _MAX_CACHE_SIZE) -> None:
        """Initialize the query cache.

        Args:
            max_size: Maximum number of cached entries.
        """
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[bool, Any]:
        """Look up a cached result.

        Args:
            key: Cache key (e.g., 'Symbol:path::Foo#function').

        Returns:
            Tuple of (found, value). If found is False, value is None.
        """
        with self._lock:
            if key in self._cache:
                self._hits += 1
                self._cache.move_to_end(key)  # LRU: mark as recently used
                return True, self._cache[key]
            self._misses += 1
            return False, None

    def put(self, key: str, value: Any) -> None:
        """Store a result in the cache.

        Args:
            key: Cache key.
            value: The model instance to cache.
        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
            else:
                if len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)  # Remove least recently used
                self._cache[key] = value

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
