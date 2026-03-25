"""Fluent query builder -- the heart of the ORM.

All filter methods return self for chaining (sync). Terminal methods execute
SQL via the async storage backend and must be awaited.

Implementation is split across mixin modules:

- where.py         -- WHERE clause methods (where, or_where, where_in, ...)
- relations.py     -- Relation filtering (has, doesnt_have, subquery builders)
- sql.py           -- SQL building (_build_where, _build_sql, _build_fts_sql)
- execution.py     -- Terminal methods (get, first, find, paginate, count, ...)
- search.py        -- FTS5 + vector search (search, similar_to, _execute_*)
- eager_loading.py -- Eager loading (_load_eager, _load_eager_counts)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sylvan.database.orm.exceptions import QueryError
from sylvan.database.orm.query.eager_loading import QueryEagerMixin
from sylvan.database.orm.query.execution import QueryExecutionMixin
from sylvan.database.orm.query.relations import QueryRelationMixin
from sylvan.database.orm.query.search import QuerySearchMixin
from sylvan.database.orm.query.sql import QuerySqlMixin
from sylvan.database.orm.query.where import QueryWhereMixin

_SAFE_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_.*"]*(?:\.[a-zA-Z_][a-zA-Z0-9_.*"]*)*$')
"""Regex pattern for validating SQL identifiers against injection."""

_SAFE_DIRECTION = frozenset({"ASC", "DESC"})
"""Allowed ORDER BY direction keywords."""


def _validate_identifier(name: str) -> str:
    """Validate a SQL identifier to prevent injection.

    Args:
        name: The identifier string to validate.

    Returns:
        The validated identifier string.

    Raises:
        QueryError: If the identifier contains invalid characters.
    """
    if not _SAFE_IDENTIFIER.match(name):
        raise QueryError(f"Invalid SQL identifier: {name!r}")
    return name


if TYPE_CHECKING:
    from sylvan.database.backends.base import StorageBackend
    from sylvan.database.orm.model.base import Model


class QueryBuilder[T: "Model"](
    QueryWhereMixin,
    QueryRelationMixin,
    QuerySqlMixin,
    QueryExecutionMixin,
    QuerySearchMixin,
    QueryEagerMixin,
):
    """Fluent SQL query builder with native FTS5 + vector search.

    Filter methods (where, join, order_by, etc.) are synchronous and return
    ``self`` for chaining.  Terminal methods (get, first, count, etc.) are
    async and must be awaited.

    Attributes:
        _debug: When True, executed queries are appended to _query_log.
        _query_log: Accumulated query log entries when debug mode is enabled.
    """

    _debug: bool = False
    _query_log: list[tuple[str, list]] = []

    @classmethod
    def enable_debug(cls) -> None:
        """Turn on query logging."""
        cls._debug = True

    @classmethod
    def disable_debug(cls) -> None:
        """Turn off query logging."""
        cls._debug = False

    @classmethod
    def get_query_log(cls) -> list[tuple[str, list]]:
        """Return a copy of the accumulated query log.

        Returns:
            List of (sql, params) tuples.
        """
        return list(cls._query_log)

    @classmethod
    def clear_query_log(cls) -> None:
        """Clear all entries from the query log."""
        cls._query_log.clear()

    def __init__(self, model_class: type[T]):
        """Initialize a builder targeting the given model class.

        Args:
            model_class: The Model subclass to build queries for.
        """
        self._model = model_class
        self._selects: list[str] = []
        self._select_raws: list[str] = []
        self._wheres: list[tuple[str, list, str]] = []
        self._joins: list[str] = []
        self._join_set: set[str] = set()
        self._order_bys: list[str] = []
        self._group_bys: list[str] = []
        self._having: list[tuple[str, list]] = []
        self._limit_val: int | None = None
        self._offset_val: int | None = None
        self._eager_loads: list[str] = []
        self._eager_counts: list[str] = []
        self._fts_query: str | None = None
        self._vec_text: str | None = None
        self._vec_vector: list[float] | None = None
        self._vec_k: int = 20
        self._vec_weight: float = 0.3
        self._include_trashed: bool = False
        self._only_trashed: bool = False

    def __repr__(self) -> str:
        """Show the SQL this builder would generate."""
        try:
            sql, params = self.to_sql()
            return f"<QueryBuilder[{self._model.__name__}] {sql} {params}>"
        except Exception:
            return f"<QueryBuilder[{self._model.__name__}]>"

    def __getattr__(self, name: str) -> Any:
        """Proxy scope calls to the model class.

        Enables chaining: ``Symbol.functions().in_repo("sylvan").get()``
        When ``.in_repo()`` is called on a QueryBuilder, we look for a scope
        with that name on the model class and apply it to THIS builder.

        Args:
            name: The attribute name to look up.

        Returns:
            A callable that applies the named scope to this builder.

        Raises:
            AttributeError: If no scope with the given name exists.
        """
        from sylvan.database.orm.primitives.scopes import ScopeDescriptor

        for cls in self._model.__mro__:
            if name in cls.__dict__:
                attr = cls.__dict__[name]
                if isinstance(attr, ScopeDescriptor):

                    def apply_scope(*args: Any, _attr: Any = attr, **kwargs: Any) -> QueryBuilder[T]:
                        """Apply a named scope to this builder."""
                        return _attr.func(self, *args, **kwargs)

                    return apply_scope
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    @property
    def backend(self) -> StorageBackend:
        """Resolve the storage backend from the application context.

        Returns:
            The active StorageBackend instance.

        Raises:
            RuntimeError: If no backend is configured.
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        return get_backend()

    def select(self, *columns: str) -> QueryBuilder[T]:
        """Specify which columns to select.

        Args:
            *columns: Column names to include in the SELECT.

        Returns:
            This builder for chaining.
        """
        self._selects.extend(columns)
        return self

    def select_raw(self, expr: str) -> QueryBuilder[T]:
        """Append a raw SQL expression to the SELECT list.

        Args:
            expr: Raw SQL expression to add.

        Returns:
            This builder for chaining.
        """
        self._select_raws.append(expr)
        return self

    def join(self, table: str, on: str, join_type: str = "JOIN") -> QueryBuilder[T]:
        """Add a JOIN clause, deduplicating by table and join type.

        Args:
            table: Table name to join.
            on: JOIN condition expression.
            join_type: Type of join (JOIN, LEFT JOIN, etc.).

        Returns:
            This builder for chaining.
        """
        _validate_identifier(table.split(maxsplit=1)[0])
        key = f"{join_type} {table}"
        if key not in self._join_set:
            self._joins.append(f"{join_type} {table} ON {on}")
            self._join_set.add(key)
        return self

    def left_join(self, table: str, on: str) -> QueryBuilder[T]:
        """Add a LEFT JOIN clause.

        Args:
            table: Table name to join.
            on: JOIN condition expression.

        Returns:
            This builder for chaining.
        """
        return self.join(table, on, "LEFT JOIN")

    def order_by(self, column: str, direction: str = "ASC") -> QueryBuilder[T]:
        """Add an ORDER BY clause.

        Args:
            column: Column name to sort by.
            direction: Sort direction (ASC or DESC).

        Returns:
            This builder for chaining.

        Raises:
            QueryError: If the direction is not ASC or DESC.
        """
        _validate_identifier(column)
        d = direction.upper()
        if d not in _SAFE_DIRECTION:
            raise QueryError(f"Invalid ORDER BY direction: {direction!r}")
        self._order_bys.append(f"{column} {d}")
        return self

    def order_by_desc(self, column: str) -> QueryBuilder[T]:
        """Shorthand for .order_by(column, "DESC").

        Args:
            column: Column name to sort by descending.

        Returns:
            This builder for chaining.
        """
        return self.order_by(column, "DESC")

    def group_by(self, *columns: str) -> QueryBuilder[T]:
        """Add GROUP BY clause(s).

        Args:
            *columns: Column names to group by.

        Returns:
            This builder for chaining.
        """
        for col in columns:
            _validate_identifier(col)
        self._group_bys.extend(columns)
        return self

    def limit(self, n: int) -> QueryBuilder[T]:
        """Limit the number of results.

        Args:
            n: Maximum number of rows to return.

        Returns:
            This builder for chaining.
        """
        self._limit_val = n
        return self

    def offset(self, n: int) -> QueryBuilder[T]:
        """Skip the first n results.

        Args:
            n: Number of rows to skip.

        Returns:
            This builder for chaining.
        """
        self._offset_val = n
        return self

    def with_(self, *relations: str) -> QueryBuilder[T]:
        """Eager-load relations to prevent N+1 queries.

        Args:
            *relations: Relation names to eager-load.

        Returns:
            This builder for chaining.
        """
        self._eager_loads.extend(relations)
        return self

    def with_count(self, relation: str) -> QueryBuilder[T]:
        """Eager-load the count of a relation as an attribute.

        Args:
            relation: Relation name to count.

        Returns:
            This builder for chaining.
        """
        self._eager_counts.append(relation)
        return self

    def when(self, condition: bool, callback: Any) -> QueryBuilder[T]:
        """Conditionally apply a query modification.

        Args:
            condition: Whether to apply the callback.
            callback: A callable receiving this builder and returning a builder.

        Returns:
            This builder (modified if condition was truthy).
        """
        if condition:
            return callback(self)
        return self

    def with_trashed(self) -> QueryBuilder[T]:
        """Include soft-deleted records in results.

        Returns:
            This builder for chaining.
        """
        self._include_trashed = True
        return self

    def only_trashed(self) -> QueryBuilder[T]:
        """Return only soft-deleted records.

        Returns:
            This builder for chaining.
        """
        self._only_trashed = True
        return self
