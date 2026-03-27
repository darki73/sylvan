"""WHERE clause mixin for QueryBuilder.

Provides all where-family filter methods and the having clause. All methods
are synchronous -- they append conditions to internal lists and return self
for chaining.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder

_UNSET = object()

_SAFE_COLUMN = re.compile(r'^(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_]*)(?:\.(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_]*))*$')

_ALLOWED_OPERATORS = frozenset(
    {
        "=",
        "!=",
        "<>",
        "<",
        ">",
        "<=",
        ">=",
        "like",
        "not like",
        "like binary",
        "glob",
        "is",
        "is not",
        "in",
        "not in",
    }
)


def _check_operator(op: str) -> str:
    """Validate and normalize an operator string.

    Args:
        op: The SQL operator to validate.

    Returns:
        The normalized (lowercased) operator.

    Raises:
        ValueError: If the operator is not in the allowed set.
    """
    normalized = op.strip().lower()
    if normalized not in _ALLOWED_OPERATORS:
        raise ValueError(f"Invalid operator: {op!r}. Allowed: {', '.join(sorted(_ALLOWED_OPERATORS))}")
    return normalized


def _validate_column(col: str) -> str:
    """Validate a column name to prevent SQL injection.

    Args:
        col: Column name to validate.

    Returns:
        The validated column name.

    Raises:
        ValueError: If the column name contains invalid characters.
    """
    if not _SAFE_COLUMN.match(col):
        raise ValueError(f"Invalid column name: {col!r}")
    return col


def _add_condition(wheres: list, col: str, val: Any, boolean: str) -> None:
    """Append a single column=value condition, handling None -> IS NULL.

    Args:
        wheres: The _wheres list to append to.
        col: Column name (validated).
        val: Value (None triggers IS NULL).
        boolean: Join type ("AND" or "OR").
    """
    _validate_column(col)
    if val is None:
        wheres.append((f"{col} IS NULL", [], boolean))
    else:
        wheres.append((f"{col} = ?", [val], boolean))


class QueryWhereMixin:
    """Mixin providing WHERE clause methods for QueryBuilder."""

    self: QueryBuilder

    def where(
        self,
        _col: str | dict | None = None,
        _op_or_val: Any = _UNSET,
        _val: Any = _UNSET,
        **kwargs: Any,
    ) -> QueryBuilder[Any]:
        """Add WHERE clause(s).

        Supports multiple styles::

            .where(kind="function")                # kwargs equality
            .where("kind", "function")             # positional equality
            .where("score", ">", 50)               # operator form
            .where({"kind": "function"})            # dict equality
            .where("name", None)                   # auto IS NULL

        Args:
            _col: Column name, dict of conditions, or None.
            _op_or_val: Operator (three-arg) or value (two-arg).
            _val: Value when using three-arg operator form.
            **kwargs: Additional column=value conditions.

        Returns:
            This builder for chaining.
        """
        if isinstance(_col, dict):
            for k, v in _col.items():
                _add_condition(self._wheres, k, v, "AND")
        elif _col is not None and _val is not _UNSET:
            _validate_column(_col)
            op = _check_operator(_op_or_val)
            if _val is None and op in ("=", "is"):
                self._wheres.append((f"{_col} IS NULL", [], "AND"))
            elif _val is None and op in ("!=", "<>", "is not"):
                self._wheres.append((f"{_col} IS NOT NULL", [], "AND"))
            else:
                self._wheres.append((f"{_col} {op} ?", [_val], "AND"))
        elif _col is not None and _op_or_val is not _UNSET:
            _add_condition(self._wheres, _col, _op_or_val, "AND")
        for k, v in kwargs.items():
            _add_condition(self._wheres, k, v, "AND")
        return self

    def or_where(
        self,
        _col: str | dict | None = None,
        _op_or_val: Any = _UNSET,
        _val: Any = _UNSET,
        **kwargs: Any,
    ) -> QueryBuilder[Any]:
        """Add WHERE clause(s) joined with OR.

        Supports the same styles as ``where()``::

            .or_where("kind", "function")          # equality
            .or_where("score", ">", 50)            # operator
            .or_where("name", None)                # auto IS NULL

        Args:
            _col: Column name, dict of conditions, or None.
            _op_or_val: Operator (three-arg) or value (two-arg).
            _val: Value when using three-arg operator form.
            **kwargs: Additional column=value conditions.

        Returns:
            This builder for chaining.
        """
        if isinstance(_col, dict):
            for k, v in _col.items():
                _add_condition(self._wheres, k, v, "OR")
        elif _col is not None and _val is not _UNSET:
            _validate_column(_col)
            op = _check_operator(_op_or_val)
            if _val is None and op in ("=", "is"):
                self._wheres.append((f"{_col} IS NULL", [], "OR"))
            elif _val is None and op in ("!=", "<>", "is not"):
                self._wheres.append((f"{_col} IS NOT NULL", [], "OR"))
            else:
                self._wheres.append((f"{_col} {op} ?", [_val], "OR"))
        elif _col is not None and _op_or_val is not _UNSET:
            _add_condition(self._wheres, _col, _op_or_val, "OR")
        for k, v in kwargs.items():
            _add_condition(self._wheres, k, v, "OR")
        return self

    def or_where_like(self, column: str, pattern: str) -> QueryBuilder[Any]:
        """Add OR column LIKE pattern clause.

        Args:
            column: Column name to match.
            pattern: SQL LIKE pattern string.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
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
        _validate_column(column)
        if not values:
            self._wheres.append(("0", [], "AND"))
            return self
        ph = ", ".join("?" for _ in values)
        self._wheres.append((f"{column} IN ({ph})", list(values), "AND"))
        return self

    def where_not(self, **kwargs: Any) -> QueryBuilder[Any]:
        """Add WHERE column != value clause(s).

        None values are converted to IS NOT NULL.

        Args:
            **kwargs: Column=value pairs to exclude.

        Returns:
            This builder for chaining.
        """
        for k, v in kwargs.items():
            _validate_column(k)
            if v is None:
                self._wheres.append((f"{k} IS NOT NULL", [], "AND"))
            else:
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
        _validate_column(column)
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
        _validate_column(column)
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
        _validate_column(column)
        self._wheres.append((f"{column} GLOB ?", [pattern], "AND"))
        return self

    def where_null(self, column: str) -> QueryBuilder[Any]:
        """Add WHERE column IS NULL clause.

        Args:
            column: Column name to check.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
        self._wheres.append((f"{column} IS NULL", [], "AND"))
        return self

    def where_not_null(self, column: str) -> QueryBuilder[Any]:
        """Add WHERE column IS NOT NULL clause.

        Args:
            column: Column name to check.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
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
        _validate_column(column)
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
        _validate_column(column)
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
        _validate_column(column)
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
        _validate_column(column)
        self._wheres.append((f"{column} NOT IN ({subquery})", params or [], "AND"))
        return self

    # ── OR variants ────────────────────────────────────────────────────

    def or_where_null(self, column: str) -> QueryBuilder[Any]:
        """Add OR column IS NULL clause.

        Args:
            column: Column name to check.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
        self._wheres.append((f"{column} IS NULL", [], "OR"))
        return self

    def or_where_not_null(self, column: str) -> QueryBuilder[Any]:
        """Add OR column IS NOT NULL clause.

        Args:
            column: Column name to check.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
        self._wheres.append((f"{column} IS NOT NULL", [], "OR"))
        return self

    def or_where_in(self, column: str, values: list) -> QueryBuilder[Any]:
        """Add OR column IN (...) clause.

        Args:
            column: Column name to filter on.
            values: List of values to match.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
        if not values:
            self._wheres.append(("0", [], "OR"))
            return self
        ph = ", ".join("?" for _ in values)
        self._wheres.append((f"{column} IN ({ph})", list(values), "OR"))
        return self

    def or_where_not_in(self, column: str, values: list) -> QueryBuilder[Any]:
        """Add OR column NOT IN (...) clause.

        Args:
            column: Column name.
            values: List of values to exclude.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
        if not values:
            return self
        ph = ", ".join("?" for _ in values)
        self._wheres.append((f"{column} NOT IN ({ph})", list(values), "OR"))
        return self

    def or_where_between(self, column: str, low: Any, high: Any) -> QueryBuilder[Any]:
        """Add OR column BETWEEN low AND high clause.

        Args:
            column: Column name to bound.
            low: Lower bound value.
            high: Upper bound value.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
        self._wheres.append((f"{column} BETWEEN ? AND ?", [low, high], "OR"))
        return self

    def or_where_not(self, **kwargs: Any) -> QueryBuilder[Any]:
        """Add OR column != value clause(s).

        None values are converted to IS NOT NULL.

        Args:
            **kwargs: Column=value pairs to exclude.

        Returns:
            This builder for chaining.
        """
        for k, v in kwargs.items():
            _validate_column(k)
            if v is None:
                self._wheres.append((f"{k} IS NOT NULL", [], "OR"))
            else:
                self._wheres.append((f"{k} != ?", [v], "OR"))
        return self

    def or_where_not_like(self, column: str, pattern: str) -> QueryBuilder[Any]:
        """Add OR column NOT LIKE pattern clause.

        Args:
            column: Column name to match.
            pattern: SQL LIKE pattern string.

        Returns:
            This builder for chaining.
        """
        _validate_column(column)
        self._wheres.append((f"{column} NOT LIKE ?", [pattern], "OR"))
        return self

    # ── Multi-column ──────────────────────────────────────────────────

    def where_any(
        self,
        columns: list[str],
        _op_or_val: Any = _UNSET,
        _val: Any = _UNSET,
    ) -> QueryBuilder[Any]:
        """Add WHERE clause matching ANY of the columns (OR group).

        Example::

            .where_any(["name", "email"], "like", "%john%")
            # WHERE (name like ? OR email like ?)

        Args:
            columns: Column names to match against.
            _op_or_val: Operator (three-arg) or value (two-arg).
            _val: Value when using three-arg operator form.

        Returns:
            This builder for chaining.
        """
        if _val is not _UNSET:
            op = _check_operator(_op_or_val)
            val = _val
        elif _op_or_val is not _UNSET:
            op = "="
            val = _op_or_val
        else:
            return self

        def _inner(q: QueryBuilder) -> None:
            for i, col in enumerate(columns):
                if i == 0:
                    if val is None and op in ("=", "is"):
                        q._wheres.append((f"{col} IS NULL", [], "AND"))
                    else:
                        q._wheres.append((f"{col} {op} ?", [val], "AND"))
                elif val is None and op in ("=", "is"):
                    q._wheres.append((f"{col} IS NULL", [], "OR"))
                else:
                    q._wheres.append((f"{col} {op} ?", [val], "OR"))

        return self.where_group(_inner)

    def where_all(
        self,
        columns: list[str],
        _op_or_val: Any = _UNSET,
        _val: Any = _UNSET,
    ) -> QueryBuilder[Any]:
        """Add WHERE clause matching ALL of the columns (AND group).

        Example::

            .where_all(["name", "email"], "!=", None)
            # WHERE (name IS NOT NULL AND email IS NOT NULL)

        Args:
            columns: Column names that must all match.
            _op_or_val: Operator (three-arg) or value (two-arg).
            _val: Value when using three-arg operator form.

        Returns:
            This builder for chaining.
        """
        if _val is not _UNSET:
            op = _check_operator(_op_or_val)
            val = _val
        elif _op_or_val is not _UNSET:
            op = "="
            val = _op_or_val
        else:
            return self

        def _inner(q: QueryBuilder) -> None:
            for col in columns:
                if val is None and op in ("=", "is"):
                    q._wheres.append((f"{col} IS NULL", [], "AND"))
                elif val is None and op in ("!=", "<>", "is not"):
                    q._wheres.append((f"{col} IS NOT NULL", [], "AND"))
                else:
                    q._wheres.append((f"{col} {op} ?", [val], "AND"))

        return self.where_group(_inner)

    def where_none(
        self,
        columns: list[str],
        _op_or_val: Any = _UNSET,
        _val: Any = _UNSET,
    ) -> QueryBuilder[Any]:
        """Add WHERE clause matching NONE of the columns (negated OR group).

        Ensures no column matches::

            .where_none(["name", "email"], "like", "%spam%")
            # WHERE NOT (name like ? OR email like ?)

        Args:
            columns: Column names that must all NOT match.
            _op_or_val: Operator (three-arg) or value (two-arg).
            _val: Value when using three-arg operator form.

        Returns:
            This builder for chaining.
        """
        if _val is not _UNSET:
            op = _check_operator(_op_or_val)
            val = _val
        elif _op_or_val is not _UNSET:
            op = "="
            val = _op_or_val
        else:
            return self

        def _inner(q: QueryBuilder) -> None:
            for i, col in enumerate(columns):
                join = "AND" if i == 0 else "OR"
                if val is None and op in ("=", "is"):
                    q._wheres.append((f"{col} IS NULL", [], join))
                else:
                    q._wheres.append((f"{col} {op} ?", [val], join))

        from sylvan.database.orm.query.builder import QueryBuilder

        inner = QueryBuilder(self._model)
        _inner(inner)
        if not inner._wheres:
            return self
        parts = []
        params: list = []
        for i, (clause, clause_params, clause_join) in enumerate(inner._wheres):
            if i > 0:
                parts.append(f" {clause_join} ")
            parts.append(clause)
            params.extend(clause_params)
        grouped = "NOT (" + "".join(parts) + ")"
        self._wheres.append((grouped, params, "AND"))
        return self

    def where_column(self, first: str, _op_or_second: str = "=", second: str | None = None) -> QueryBuilder[Any]:
        """Add WHERE clause comparing two columns.

        Example::

            .where_column("updated_at", ">", "created_at")
            .where_column("first_name", "last_name")   # equality

        Args:
            first: First column name.
            _op_or_second: Operator (three-arg) or second column (two-arg).
            second: Second column when using three-arg form.

        Returns:
            This builder for chaining.
        """
        if second is not None:
            op = _check_operator(_op_or_second)
            col2 = second
        else:
            op = "="
            col2 = _op_or_second
        self._wheres.append((f"{first} {op} {col2}", [], "AND"))
        return self

    # ── Grouping ─────────────────────────────────────────────────────

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
