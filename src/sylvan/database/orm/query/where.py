"""WHERE clause mixin for QueryBuilder.

Provides all where-family filter methods and the having clause. All methods
are synchronous — they append conditions to internal lists and return self
for chaining.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder


class QueryWhereMixin:
    """Mixin providing WHERE clause methods for QueryBuilder."""

    self: QueryBuilder

    def where(self, _col: str | dict | None = None, _val: Any = None, **kwargs: Any) -> QueryBuilder[Any]:
        """Add WHERE clause(s).

        Three styles::

            .where(kind="function")                # kwargs
            .where("kind", "function")             # positional
            .where({"kind": "function"})            # dict

        Args:
            _col: Column name, dict of conditions, or None.
            _val: Value to match when _col is a string.
            **kwargs: Additional column=value conditions.

        Returns:
            This builder for chaining.
        """
        if isinstance(_col, dict):
            for k, v in _col.items():
                self._wheres.append((f"{k} = ?", [v], "AND"))
        elif _col is not None and _val is not None:
            self._wheres.append((f"{_col} = ?", [_val], "AND"))
        for k, v in kwargs.items():
            self._wheres.append((f"{k} = ?", [v], "AND"))
        return self

    def or_where(self, _col: str | dict | None = None, _val: Any = None, **kwargs: Any) -> QueryBuilder[Any]:
        """Add WHERE clause(s) joined with OR.

        Args:
            _col: Column name, dict of conditions, or None.
            _val: Value to match when _col is a string.
            **kwargs: Additional column=value conditions.

        Returns:
            This builder for chaining.
        """
        if isinstance(_col, dict):
            for k, v in _col.items():
                self._wheres.append((f"{k} = ?", [v], "OR"))
        elif _col is not None and _val is not None:
            self._wheres.append((f"{_col} = ?", [_val], "OR"))
        for k, v in kwargs.items():
            self._wheres.append((f"{k} = ?", [v], "OR"))
        return self

    def or_where_like(self, column: str, pattern: str) -> QueryBuilder[Any]:
        """Add OR column LIKE pattern clause.

        Args:
            column: Column name to match.
            pattern: SQL LIKE pattern string.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} LIKE ?", [pattern], "OR"))
        return self

    def where_in(self, column: str, values: list) -> QueryBuilder[Any]:
        """Add WHERE column IN (...) clause.

        Args:
            column: Column name to filter on.
            values: List of values to match.

        Returns:
            This builder for chaining.
        """
        if not values:
            self._wheres.append(("0", [], "AND"))
            return self
        ph = ", ".join("?" for _ in values)
        self._wheres.append((f"{column} IN ({ph})", list(values), "AND"))
        return self

    def where_not(self, **kwargs: Any) -> QueryBuilder[Any]:
        """Add WHERE column != value clause(s).

        Args:
            **kwargs: Column=value pairs to exclude.

        Returns:
            This builder for chaining.
        """
        for k, v in kwargs.items():
            self._wheres.append((f"{k} != ?", [v], "AND"))
        return self

    def where_like(self, column: str, pattern: str) -> QueryBuilder[Any]:
        """Add WHERE column LIKE pattern clause.

        Args:
            column: Column name to match.
            pattern: SQL LIKE pattern string.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} LIKE ?", [pattern], "AND"))
        return self

    def where_not_like(self, column: str, pattern: str) -> QueryBuilder[Any]:
        """Add WHERE column NOT LIKE pattern clause.

        Args:
            column: Column name to match.
            pattern: SQL LIKE pattern string.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} NOT LIKE ?", [pattern], "AND"))
        return self

    def where_glob(self, column: str, pattern: str) -> QueryBuilder[Any]:
        """Add WHERE column GLOB pattern clause.

        Args:
            column: Column name to match.
            pattern: GLOB pattern string.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} GLOB ?", [pattern], "AND"))
        return self

    def where_null(self, column: str) -> QueryBuilder[Any]:
        """Add WHERE column IS NULL clause.

        Args:
            column: Column name to check.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} IS NULL", [], "AND"))
        return self

    def where_not_null(self, column: str) -> QueryBuilder[Any]:
        """Add WHERE column IS NOT NULL clause.

        Args:
            column: Column name to check.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} IS NOT NULL", [], "AND"))
        return self

    def where_raw(self, sql: str, params: list | None = None) -> QueryBuilder[Any]:
        """Add a raw SQL WHERE clause.

        Args:
            sql: Raw SQL condition.
            params: Optional parameter list for the clause.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((sql, params or [], "AND"))
        return self

    def or_where_raw(self, sql: str, params: list | None = None) -> QueryBuilder[Any]:
        """Add a raw SQL clause joined with OR.

        Args:
            sql: Raw SQL condition.
            params: Optional parameter list for the clause.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((sql, params or [], "OR"))
        return self

    def where_between(self, column: str, low: Any, high: Any) -> QueryBuilder[Any]:
        """Add WHERE column BETWEEN low AND high clause.

        Args:
            column: Column name to bound.
            low: Lower bound value.
            high: Upper bound value.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} BETWEEN ? AND ?", [low, high], "AND"))
        return self

    def where_exists(self, subquery: str, params: list | None = None) -> QueryBuilder[Any]:
        """Add WHERE EXISTS (subquery) clause.

        Args:
            subquery: SQL subquery string.
            params: Optional parameter list.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"EXISTS ({subquery})", params or [], "AND"))
        return self

    def where_in_subquery(self, column: str, subquery: str, params: list | None = None) -> QueryBuilder[Any]:
        """Add WHERE column IN (subquery) clause.

        Args:
            column: Column name to filter.
            subquery: SQL subquery string.
            params: Optional parameter list.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} IN ({subquery})", params or [], "AND"))
        return self

    def where_not_in(self, column: str, values: list) -> QueryBuilder[Any]:
        """Add WHERE column NOT IN (...) clause.

        Args:
            column: Column name.
            values: List of values to exclude.

        Returns:
            This builder for chaining.
        """
        if not values:
            return self
        placeholders = ", ".join("?" for _ in values)
        self._wheres.append((f"{column} NOT IN ({placeholders})", list(values), "AND"))
        return self

    def where_not_in_subquery(self, column: str, subquery: str, params: list | None = None) -> QueryBuilder[Any]:
        """Add WHERE column NOT IN (subquery) clause.

        Args:
            column: Column name to filter.
            subquery: SQL subquery string.
            params: Optional parameter list.

        Returns:
            This builder for chaining.
        """
        self._wheres.append((f"{column} NOT IN ({subquery})", params or [], "AND"))
        return self

    def where_group(self, callback: Any, *, join: str = "AND") -> QueryBuilder[Any]:
        """Add a grouped WHERE clause with parentheses.

        The callback receives a fresh builder whose conditions are
        collected and wrapped in ``(...)``.

        Args:
            callback: Function receiving a builder to define inner conditions.
            join: How to join this group with existing clauses (AND/OR).

        Returns:
            This builder for chaining.

        Example::

            query.where_group(lambda q: (
                q.where_null("summary")
                 .or_where("summary", "")
            ))
            # Produces: WHERE (summary IS NULL OR summary = ?)
        """
        from sylvan.database.orm.query.builder import QueryBuilder
        inner = QueryBuilder(self._model)
        callback(inner)
        if not inner._wheres:
            return self
        parts = []
        params: list = []
        for i, (clause, clause_params, clause_join) in enumerate(inner._wheres):
            if i > 0:
                parts.append(f" {clause_join} ")
            parts.append(clause)
            params.extend(clause_params)
        grouped = "(" + "".join(parts) + ")"
        self._wheres.append((grouped, params, join))
        return self

    def or_where_group(self, callback: Any) -> QueryBuilder[Any]:
        """Add a grouped WHERE clause joined with OR.

        Args:
            callback: Function receiving a builder to define inner conditions.

        Returns:
            This builder for chaining.
        """
        return self.where_group(callback, join="OR")

    def having(self, clause: str, *params: Any) -> QueryBuilder[Any]:
        """Add a HAVING clause (used after GROUP BY).

        Args:
            clause: SQL HAVING condition.
            *params: Parameter values for the clause.

        Returns:
            This builder for chaining.
        """
        self._having.append((clause, list(params)))
        return self
