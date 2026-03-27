"""Identity map -- ensures each database row maps to exactly one Python object per request."""

from typing import Any

_DEFAULT_MAX_SIZE = 2000


class IdentityMap:
    """Per-request cache mapping (model_class, pk) to model instances.

    When a model is loaded from the database, it's stored in the map.
    Subsequent loads of the same (class, pk) return the cached instance
    instead of creating a new Python object.

    Includes a size limit to prevent unbounded memory growth on large queries.
    When the limit is reached, the oldest entries are evicted (FIFO).

    Attributes:
        _map: The underlying cache dict.
        _max_size: Maximum number of entries before eviction.
    """

    def __init__(self, max_size: int = _DEFAULT_MAX_SIZE) -> None:
        """Initialize an empty identity map.

        Args:
            max_size: Maximum number of entries (0 = unlimited).
        """
        self._map: dict[tuple[type, Any], Any] = {}
        self._max_size = max_size

    def get(self, model_class: type, pk_value: Any) -> Any | None:
        """Look up a cached instance.

        Args:
            model_class: The model class (e.g., Symbol).
            pk_value: The primary key value.

        Returns:
            The cached instance, or None if not in the map.
        """
        return self._map.get((model_class, pk_value))

    def put(self, model_class: type, pk_value: Any, instance: Any) -> None:
        """Store an instance in the map.

        Evicts the oldest entry if the map exceeds max_size.

        Args:
            model_class: The model class.
            pk_value: The primary key value.
            instance: The model instance to cache.
        """
        if pk_value is None:
            return
        key = (model_class, pk_value)
        self._map[key] = instance
        if self._max_size and len(self._map) > self._max_size:
            oldest_key = next(iter(self._map))
            del self._map[oldest_key]

    def remove(self, model_class: type, pk_value: Any) -> None:
        """Remove an instance from the map (e.g., after delete).

        Args:
            model_class: The model class.
            pk_value: The primary key value.
        """
        self._map.pop((model_class, pk_value), None)

    def clear(self) -> None:
        """Clear the entire map."""
        self._map.clear()

    def __len__(self) -> int:
        """Return the number of cached instances.

        Returns:
            Number of entries in the map.
        """
        return len(self._map)
