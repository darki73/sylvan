"""Identity map — ensures each database row maps to exactly one Python object per request."""

from typing import Any


class IdentityMap:
    """Per-request cache mapping (model_class, pk) to model instances.

    When a model is loaded from the database, it's stored in the map.
    Subsequent loads of the same (class, pk) return the cached instance
    instead of creating a new Python object.

    Attributes:
        _map: The underlying cache dict.
    """

    def __init__(self) -> None:
        """Initialize an empty identity map.
        """
        self._map: dict[tuple[type, Any], Any] = {}

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

        Args:
            model_class: The model class.
            pk_value: The primary key value.
            instance: The model instance to cache.
        """
        if pk_value is not None:
            self._map[(model_class, pk_value)] = instance

    def remove(self, model_class: type, pk_value: Any) -> None:
        """Remove an instance from the map (e.g., after delete).

        Args:
            model_class: The model class.
            pk_value: The primary key value.
        """
        self._map.pop((model_class, pk_value), None)

    def clear(self) -> None:
        """Clear the entire map.
        """
        self._map.clear()

    def __len__(self) -> int:
        """Return the number of cached instances.

        Returns:
            Number of entries in the map.
        """
        return len(self._map)
