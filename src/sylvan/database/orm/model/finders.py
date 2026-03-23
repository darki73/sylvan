"""Query entry points that return QueryBuilder instances.

Model inherits from _QueryMixin, so all classmethods remain available
on Model itself.  Methods that return QueryBuilder instances (lazy) stay
sync.  Methods that hit the database (find, find_or_fail) are async.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sylvan.database.orm.exceptions import ModelNotFoundError, QueryError
from sylvan.database.orm.query.builder import QueryBuilder

if TYPE_CHECKING:
    from sylvan.database.orm.model.base import Model


class _QueryMixin:
    """Query shortcuts that return QueryBuilder instances.

    Mixed into Model to keep the main file focused on construction and identity.
    """

    @classmethod
    def query(cls) -> QueryBuilder:
        """Return a fresh QueryBuilder for this model.

        Returns:
            A new QueryBuilder targeting this model.
        """
        return QueryBuilder(cls)

    @classmethod
    def all(cls) -> QueryBuilder:
        """Return a QueryBuilder that selects all records.

        Returns:
            A new QueryBuilder targeting this model.
        """
        return QueryBuilder(cls)

    @classmethod
    def where(cls, _col: str | dict | None = None, _val: Any = None, **kwargs: Any) -> QueryBuilder:
        """Start a filtered query with WHERE clause(s).

        Args:
            _col: Column name, dict of conditions, or None.
            _val: Value to match when _col is a string.
            **kwargs: Additional column=value conditions.

        Returns:
            A QueryBuilder with the WHERE clauses applied.
        """
        return QueryBuilder(cls).where(_col, _val, **kwargs)

    @classmethod
    def where_in(cls, column: str, values: list) -> QueryBuilder:
        """Start a query with a WHERE column IN (...) clause.

        Args:
            column: Column name to filter on.
            values: List of values to match.

        Returns:
            A QueryBuilder with the WHERE IN clause applied.
        """
        return QueryBuilder(cls).where_in(column, values)

    @classmethod
    def where_not(cls, **kwargs: Any) -> QueryBuilder:
        """Start a query with WHERE column != value clause(s).

        Args:
            **kwargs: Column=value pairs to exclude.

        Returns:
            A QueryBuilder with the WHERE != clauses applied.
        """
        return QueryBuilder(cls).where_not(**kwargs)

    @classmethod
    def where_like(cls, column: str, pattern: str) -> QueryBuilder:
        """Start a query with a WHERE column LIKE pattern clause.

        Args:
            column: Column name to match.
            pattern: SQL LIKE pattern string.

        Returns:
            A QueryBuilder with the WHERE LIKE clause applied.
        """
        return QueryBuilder(cls).where_like(column, pattern)

    @classmethod
    def where_null(cls, column: str) -> QueryBuilder:
        """Start a query with a WHERE column IS NULL clause.

        Args:
            column: Column name to check for NULL.

        Returns:
            A QueryBuilder with the WHERE IS NULL clause applied.
        """
        return QueryBuilder(cls).where_null(column)

    @classmethod
    def where_not_null(cls, column: str) -> QueryBuilder:
        """Start a query with a WHERE column IS NOT NULL clause.

        Args:
            column: Column name to check for non-NULL.

        Returns:
            A QueryBuilder with the WHERE IS NOT NULL clause applied.
        """
        return QueryBuilder(cls).where_not_null(column)

    @classmethod
    def search(cls, query: str) -> QueryBuilder:
        """Start an FTS5 full-text search query.

        Args:
            query: The search terms.

        Returns:
            A QueryBuilder with FTS5 search configured.

        Raises:
            QueryError: If the model has no FTS5 table configured.
        """
        if cls.__fts_table__ is None:
            raise QueryError(f"{cls.__name__} has no FTS5 table configured")
        return QueryBuilder(cls).search(query)

    @classmethod
    def similar_to(cls, text_or_vector: str | list[float], k: int = 20,
                   weight: float = 0.3) -> QueryBuilder:
        """Start a vector similarity search query.

        Args:
            text_or_vector: Text string (will be embedded) or raw float vector.
            k: Number of nearest neighbors to retrieve.
            weight: Vector weight in hybrid search (0-1).

        Returns:
            A QueryBuilder with vector search configured.

        Raises:
            QueryError: If the model has no vector table configured.
        """
        if cls.__vec_table__ is None:
            raise QueryError(f"{cls.__name__} has no vector table configured")
        return QueryBuilder(cls).similar_to(text_or_vector, k=k, weight=weight)

    @classmethod
    async def find(cls, pk_value: Any) -> Model | None:
        """Find a single record by primary key, returning None if not found.

        Args:
            pk_value: The primary key value to search for.

        Returns:
            The matching model instance, or None if not found.
        """
        return await QueryBuilder(cls).where(cls._pk_column, pk_value).first()

    @classmethod
    async def find_or_fail(cls, pk_value: Any) -> Model:
        """Find a single record by primary key, raising ModelNotFoundError if absent.

        Args:
            pk_value: The primary key value to search for.

        Returns:
            The matching model instance.

        Raises:
            ModelNotFoundError: If no record matches the primary key.
        """
        result = await cls.find(pk_value)
        if result is None:
            raise ModelNotFoundError(f"{cls.__name__} not found: {pk_value}")
        return result
