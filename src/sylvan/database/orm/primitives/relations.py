"""Relationship descriptors -- BelongsTo, HasMany, HasOne, BelongsToMany.

Eager-loadable via ``QueryBuilder.with_()``.  Lazy sync loading is no longer
supported because the ORM is fully async.  Accessing a relation that has not
been eager-loaded or explicitly loaded via ``await instance.load("rel")``
returns a sentinel or raises ``RelationNotLoadedError``.
"""

from __future__ import annotations

from typing import Any

_NOT_LOADED = object()
"""Sentinel distinguishing 'not loaded' from 'loaded but None/empty'."""


class RelationNotLoadedError(AttributeError):
    """Raised when accessing a relation that has not been loaded.

    Use ``await instance.load("relation_name")`` or
    ``await Model.where(...).with_("relation_name").get()`` to load it first.
    """


def _resolve_model(ref: str | type) -> type:
    """Resolve a string model reference to the actual class.

    Args:
        ref: A model class or its name as a string.

    Returns:
        The resolved model class.
    """
    if isinstance(ref, str):
        from sylvan.database.orm.runtime.model_registry import get_model
        return get_model(ref)
    return ref


class RelationDescriptor:
    """Base class for relationship descriptors.

    Subclasses implement ``__get__`` to return cached (eager-loaded) values
    or raise ``RelationNotLoadedError``.

    Attributes:
        foreign_key: Column name holding the foreign key.
        local_key: Column name on the owning side to match against.
    """

    def __init__(
        self,
        related: str | type,
        foreign_key: str,
        local_key: str = "id",
    ):
        """Define a relation to another model.

        Args:
            related: The related model class or its name as a string.
            foreign_key: Column name holding the foreign key.
            local_key: Column name on the owning side to match against.
        """
        self._related_ref = related
        self.foreign_key = foreign_key
        self.local_key = local_key
        self._attr_name: str = ""

    @property
    def related_model(self) -> type:
        """Resolve and return the related model class."""
        return _resolve_model(self._related_ref)

    def __set_name__(self, owner: type, name: str) -> None:
        """Record the attribute name when the descriptor is assigned to a class.

        Args:
            owner: The class that owns this descriptor.
            name: The attribute name assigned to this descriptor.
        """
        self._attr_name = name


class BelongsTo(RelationDescriptor):
    """Many-to-one relationship. The foreign key is on THIS model.

    Returns the cached value if eager-loaded or explicitly loaded.
    Returns None if the foreign key is None. Raises RelationNotLoadedError
    if the relation has not been loaded.
    """

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Return the related instance from cache, or raise RelationNotLoadedError.

        Args:
            obj: The model instance, or None when accessed on the class.
            objtype: The model class.

        Returns:
            The related model instance, None, or the descriptor itself (class access).

        Raises:
            RelationNotLoadedError: If the relation has not been loaded yet.
        """
        if obj is None:
            return self

        cache_key = f"_rel_{self._attr_name}"
        cached = getattr(obj, cache_key, _NOT_LOADED)
        if cached is not _NOT_LOADED:
            return cached

        # If the FK is None, there's nothing to load
        fk_value = getattr(obj, self.foreign_key, None)
        if fk_value is None:
            return None

        raise RelationNotLoadedError(
            f"Relation '{self._attr_name}' on {type(obj).__name__} has not been loaded. "
            f"Use 'await instance.load(\"{self._attr_name}\")' or "
            f"'.with_(\"{self._attr_name}\")' in your query."
        )


class HasMany(RelationDescriptor):
    """One-to-many relationship. The foreign key is on the RELATED model.

    Returns the cached list if eager-loaded or explicitly loaded.
    Raises RelationNotLoadedError if the relation has not been loaded.
    """

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Return a list of related instances from cache, or raise RelationNotLoadedError.

        Args:
            obj: The model instance, or None when accessed on the class.
            objtype: The model class.

        Returns:
            A list of related instances, or the descriptor itself (class access).

        Raises:
            RelationNotLoadedError: If the relation has not been loaded yet.
        """
        if obj is None:
            return self

        cache_key = f"_rel_{self._attr_name}"
        cached = getattr(obj, cache_key, _NOT_LOADED)
        if cached is not _NOT_LOADED:
            return cached

        local_value = getattr(obj, self.local_key, None)
        if local_value is None:
            return []

        raise RelationNotLoadedError(
            f"Relation '{self._attr_name}' on {type(obj).__name__} has not been loaded. "
            f"Use 'await instance.load(\"{self._attr_name}\")' or "
            f"'.with_(\"{self._attr_name}\")' in your query."
        )


class HasOne(RelationDescriptor):
    """One-to-one relationship. The foreign key is on the RELATED model.

    Returns the cached value if eager-loaded or explicitly loaded.
    Raises RelationNotLoadedError if the relation has not been loaded.
    """

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Return the related instance from cache, or raise RelationNotLoadedError.

        Args:
            obj: The model instance, or None when accessed on the class.
            objtype: The model class.

        Returns:
            The related instance, None, or the descriptor itself (class access).

        Raises:
            RelationNotLoadedError: If the relation has not been loaded yet.
        """
        if obj is None:
            return self

        cache_key = f"_rel_{self._attr_name}"
        cached = getattr(obj, cache_key, _NOT_LOADED)
        if cached is not _NOT_LOADED:
            return cached

        local_value = getattr(obj, self.local_key, None)
        if local_value is None:
            return None

        raise RelationNotLoadedError(
            f"Relation '{self._attr_name}' on {type(obj).__name__} has not been loaded. "
            f"Use 'await instance.load(\"{self._attr_name}\")' or "
            f"'.with_(\"{self._attr_name}\")' in your query."
        )


class BelongsToMany(RelationDescriptor):
    """Many-to-many via pivot table.

    Returns the cached list if eager-loaded or explicitly loaded.
    Raises RelationNotLoadedError if the relation has not been loaded.

    Attributes:
        pivot_table: Name of the join/pivot table.
        related_key: Column in the pivot table referencing the related model.
    """

    def __init__(self, related, pivot_table, foreign_key, related_key, local_key="id"):
        """Define a many-to-many relation through a pivot table.

        Args:
            related: The related model class or its name as a string.
            pivot_table: Name of the join/pivot table.
            foreign_key: Column in the pivot table referencing this model.
            related_key: Column in the pivot table referencing the related model.
            local_key: Column on this model to match against.
        """
        super().__init__(related, foreign_key=foreign_key, local_key=local_key)
        self.pivot_table = pivot_table
        self.related_key = related_key

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Return a list of related instances from cache, or raise RelationNotLoadedError.

        Args:
            obj: The model instance, or None when accessed on the class.
            objtype: The model class.

        Returns:
            A list of related instances, or the descriptor itself (class access).

        Raises:
            RelationNotLoadedError: If the relation has not been loaded yet.
        """
        if obj is None:
            return self

        cache_key = f"_rel_{self._attr_name}"
        cached = getattr(obj, cache_key, _NOT_LOADED)
        if cached is not _NOT_LOADED:
            return cached

        local_value = getattr(obj, self.local_key, None)
        if local_value is None:
            return []

        raise RelationNotLoadedError(
            f"Relation '{self._attr_name}' on {type(obj).__name__} has not been loaded. "
            f"Use 'await instance.load(\"{self._attr_name}\")' or "
            f"'.with_(\"{self._attr_name}\")' in your query."
        )
