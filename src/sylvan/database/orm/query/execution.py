"""Execution mixin for QueryBuilder.

Terminal methods that execute SQL and return results.  All methods are async
and use the storage backend from the application context.
"""

from __future__ import annotations

import inspect
import math
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from sylvan.database.orm.model.base import Model
    from sylvan.database.orm.query.builder import QueryBuilder

T = TypeVar("T")


class _AggregateExpr:
    """Base class for aggregate expressions used with ``aggregates()``.

    Attributes:
        column: Column to aggregate.
        func: SQL aggregate function name.
    """

    __slots__ = ("column", "func")

    def __init__(self, column: str, func: str) -> None:
        self.column = column
        self.func = func

    def to_sql(self, alias: str) -> str:
        """Compile to SQL fragment.

        Args:
            alias: Output alias for the result.

        Returns:
            SQL like ``COALESCE(SUM(col), 0) AS alias``.
        """
        return f"COALESCE({self.func}({self.column}), 0) AS {alias}"


class Sum(_AggregateExpr):
    """SUM aggregate expression.

    Example::

        totals = await Model.all().aggregates(total=Sum("amount"))
    """

    def __init__(self, column: str) -> None:
        super().__init__(column, "SUM")


class Avg(_AggregateExpr):
    """AVG aggregate expression."""

    def __init__(self, column: str) -> None:
        super().__init__(column, "AVG")


class Max(_AggregateExpr):
    """MAX aggregate expression. Returns NULL (not 0) for empty sets."""

    def __init__(self, column: str) -> None:
        super().__init__(column, "MAX")

    def to_sql(self, alias: str) -> str:
        return f"{self.func}({self.column}) AS {alias}"


class Min(_AggregateExpr):
    """MIN aggregate expression. Returns NULL (not 0) for empty sets."""

    def __init__(self, column: str) -> None:
        super().__init__(column, "MIN")

    def to_sql(self, alias: str) -> str:
        return f"{self.func}({self.column}) AS {alias}"


class Count(_AggregateExpr):
    """COUNT aggregate expression.

    Example::

        stats = await Model.all().aggregates(
            total=Count(),
            unique_days=Count("date", distinct=True),
        )
    """

    def __init__(self, column: str = "*", *, distinct: bool = False) -> None:
        col_expr = f"DISTINCT {column}" if distinct else column
        super().__init__(col_expr, "COUNT")


class QueryExecutionMixin:
    """Mixin providing async query execution methods for QueryBuilder."""

    self: QueryBuilder

    async def get(self: QueryBuilder[T]) -> list:
        """Execute the query and return a list of model instances.

        Returns:
            List of model instances matching the query.
        """
        has_fts = self._fts_query is not None
        has_vec = self._vec_text is not None or self._vec_vector is not None

        if has_fts and has_vec:
            return await self._execute_hybrid()
        if has_vec:
            return await self._execute_vector()

        sql, params = self._build_sql()
        self._log_query(sql, params)
        rows = await self.backend.fetch_all(sql, params)
        instances = [self._model._from_row(dict(r) if not isinstance(r, dict) else r) for r in rows]

        if self._eager_loads:
            await self._load_eager(instances)
        if self._eager_counts:
            await self._load_eager_counts(instances)

        return instances

    async def first(self: QueryBuilder[T]) -> T | None:
        """Return the first result or None.

        Returns:
            The first matching model instance, or None.
        """
        self._limit_val = 1
        results = await self.get()
        return results[0] if results else None

    async def find(self: QueryBuilder[T], pk_value: Any) -> T | None:
        """Find a single record by primary key.

        Args:
            pk_value: The primary key value to search for.

        Returns:
            The matching model instance, or None.
        """
        return await self.where(self._model._pk_column, pk_value).first()

    async def find_or_fail(self: QueryBuilder[T], pk_value: Any) -> T:
        """Find by primary key, raising ModelNotFoundError if absent.

        Args:
            pk_value: The primary key value to search for.

        Returns:
            The matching model instance.

        Raises:
            ModelNotFoundError: If no record matches.
        """
        from sylvan.database.orm.exceptions import ModelNotFoundError

        result = await self.find(pk_value)
        if result is None:
            raise ModelNotFoundError(f"{self._model.__name__} not found: {pk_value}")
        return result

    def to_sql(self) -> tuple[str, list]:
        """Return the generated SQL and params without executing.

        Returns:
            Tuple of (SQL string, parameter list).
        """
        return self._build_sql()

    def to_subquery(self, column: str) -> str:
        """Build a SELECT subquery for a single column without executing.

        Returns a SQL string suitable for use with ``where_in_subquery``
        or ``where_not_in_subquery``.

        Args:
            column: The column to select in the subquery.

        Returns:
            SQL string like ``SELECT id FROM files WHERE repo_id = 1``.

        Example::

            files_q = FileRecord.where(repo_id=1).to_subquery("id")
            symbols_q = Symbol.query().where_in_subquery("file_id", files_q).to_subquery("symbol_id")
            await Reference.query().where_in_subquery("source_symbol_id", symbols_q).delete()
        """
        sql, params = self._build_sql(select_override=column)
        if params:
            for param in params:
                if param is None:
                    sql = sql.replace("?", "NULL", 1)
                elif isinstance(param, str):
                    escaped = param.replace("'", "''")
                    sql = sql.replace("?", f"'{escaped}'", 1)
                elif isinstance(param, bool):
                    sql = sql.replace("?", "1" if param else "0", 1)
                else:
                    sql = sql.replace("?", str(param), 1)
        return sql

    async def paginate(self: QueryBuilder[T], page: int = 1, per_page: int = 20) -> dict:
        """Return paginated results.

        Args:
            page: Page number (1-indexed).
            per_page: Number of results per page.

        Returns:
            Dict with keys: data, total, page, per_page, pages.
        """
        count_sql, count_params = self._build_sql(select_override="COUNT(*)")
        self._log_query(count_sql, count_params)
        row = await self.backend.fetch_one(count_sql, count_params)
        total = next(iter(row.values())) if row else 0
        pages = math.ceil(total / per_page) if per_page > 0 else 0

        saved_limit, saved_offset = self._limit_val, self._offset_val
        self._limit_val = per_page
        self._offset_val = (page - 1) * per_page
        data = await self.get()
        self._limit_val, self._offset_val = saved_limit, saved_offset

        return {
            "data": data,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }

    async def count(self) -> int | dict:
        """Count results. With group_by, returns {group_val: count}.

        Returns:
            An integer count, or a dict mapping group keys to counts.
        """
        if self._group_bys:
            gb = ", ".join(self._group_bys)
            sql, params = self._build_sql(select_override=f"{gb}, COUNT(*) as _cnt")
            rows = await self.backend.fetch_all(sql, params)
            if len(self._group_bys) == 1:
                return {next(iter(r.values())): list(r.values())[-1] for r in rows}
            return {tuple(list(r.values())[:-1]): list(r.values())[-1] for r in rows}

        sql, params = self._build_sql(select_override="COUNT(*)")
        row = await self.backend.fetch_one(sql, params)
        return next(iter(row.values())) if row else 0

    async def _aggregate(self, func: str, column: str) -> int | float | dict:
        """Run an aggregate function on a column.

        With group_by, returns ``{group_val: aggregate}``.

        Args:
            func: SQL aggregate function (SUM, AVG, MAX, MIN).
            column: Column to aggregate.

        Returns:
            Scalar result, or dict when grouped.
        """
        expr = f"COALESCE({func}({column}), 0)"
        if self._group_bys:
            gb = ", ".join(self._group_bys)
            sql, params = self._build_sql(select_override=f"{gb}, {expr} as _agg")
            rows = await self.backend.fetch_all(sql, params)
            if len(self._group_bys) == 1:
                return {next(iter(r.values())): list(r.values())[-1] for r in rows}
            return {tuple(list(r.values())[:-1]): list(r.values())[-1] for r in rows}

        sql, params = self._build_sql(select_override=expr)
        row = await self.backend.fetch_one(sql, params)
        return next(iter(row.values())) if row else 0

    async def sum(self, column: str) -> int | float | dict:
        """Sum a column. With group_by, returns ``{group_val: sum}``.

        Args:
            column: Column to sum.

        Returns:
            Scalar sum, or dict when grouped.
        """
        return await self._aggregate("SUM", column)

    async def avg(self, column: str) -> float | dict:
        """Average a column. With group_by, returns ``{group_val: avg}``.

        Args:
            column: Column to average.

        Returns:
            Scalar average, or dict when grouped.
        """
        return await self._aggregate("AVG", column)

    async def max(self, column: str) -> int | float | str | dict:
        """Get the maximum value. With group_by, returns ``{group_val: max}``.

        Args:
            column: Column to find the max of.

        Returns:
            Scalar max, or dict when grouped.
        """
        return await self._aggregate("MAX", column)

    async def min(self, column: str) -> int | float | str | dict:
        """Get the minimum value. With group_by, returns ``{group_val: min}``.

        Args:
            column: Column to find the min of.

        Returns:
            Scalar min, or dict when grouped.
        """
        return await self._aggregate("MIN", column)

    async def aggregates(self, **expressions: _AggregateExpr) -> dict:
        """Run multiple aggregate functions in a single query.

        Args:
            **expressions: Named aggregate expressions (Sum, Avg, Max, Min, Count).

        Returns:
            Dict mapping each keyword name to its aggregate result.

        Example::

            totals = await CodingSession.all().aggregates(
                eff_ret=Sum("total_efficiency_returned"),
                eff_eq=Sum("total_efficiency_equivalent"),
                calls=Sum("total_tool_calls"),
            )
        """
        select_parts = [expr.to_sql(alias) for alias, expr in expressions.items()]
        sql, params = self._build_sql(select_override=", ".join(select_parts))
        row = await self.backend.fetch_one(sql, params)
        if row is None:
            return {alias: 0 for alias in expressions}
        return {alias: row.get(alias, 0) or 0 for alias in expressions}

    async def exists(self) -> bool:
        """Check if any records match the query.

        Returns:
            True if at least one record matches.
        """
        saved_limit = self._limit_val
        self._limit_val = 1
        sql, params = self._build_sql(select_override="1")
        self._limit_val = saved_limit
        row = await self.backend.fetch_one(sql, params)
        return row is not None

    async def pluck(self, column: str) -> list:
        """Return a flat list of a single column's values.

        Args:
            column: Column name to extract.

        Returns:
            List of scalar values from the specified column.
        """
        from sylvan.database.orm.query.where import _validate_column

        _validate_column(column)
        sql, params = self._build_sql(select_override=column)
        rows = await self.backend.fetch_all(sql, params)
        return [next(iter(r.values())) for r in rows]

    async def delete(self) -> int:
        """Bulk delete matching rows.

        Returns:
            The number of rows deleted.
        """
        table = self._model.__table__
        where_sql, params = self._build_where()
        sql = f"DELETE FROM {table}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        return await self.backend.execute(self._translate_placeholders(sql), params)

    async def update(self, **values: Any) -> int:
        """Bulk update matching rows.

        Args:
            **values: Column=value pairs to set.

        Returns:
            The number of rows updated.
        """
        table = self._model.__table__
        fields = self._model._get_fields()

        set_parts: list[str] = []
        set_params: list[Any] = []
        for col, val in values.items():
            field = fields.get(col)
            if field:
                val = field.to_db(val)
            set_parts.append(f"{col} = ?")
            set_params.append(val)

        where_sql, where_params = self._build_where()
        sql = f"UPDATE {table} SET {', '.join(set_parts)}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        return await self.backend.execute(self._translate_placeholders(sql), set_params + where_params)

    async def increment(self, column: str, amount: int | float = 1, **extra: Any) -> int:
        """Increment a column's value on matching rows.

        Args:
            column: Column to increment.
            amount: Amount to add (default 1).
            **extra: Additional columns to update alongside the increment.

        Returns:
            Number of rows updated.
        """
        table = self._model.__table__
        fields = self._model._get_fields()
        set_parts = [f"{column} = {column} + ?"]
        set_params: list[Any] = [amount]
        for col, val in extra.items():
            field = fields.get(col)
            if field:
                val = field.to_db(val)
            set_parts.append(f"{col} = ?")
            set_params.append(val)
        where_sql, where_params = self._build_where()
        sql = f"UPDATE {table} SET {', '.join(set_parts)}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        return await self.backend.execute(self._translate_placeholders(sql), set_params + where_params)

    async def decrement(self, column: str, amount: int | float = 1, **extra: Any) -> int:
        """Decrement a column's value on matching rows.

        Args:
            column: Column to decrement.
            amount: Amount to subtract (default 1).
            **extra: Additional columns to update alongside the decrement.

        Returns:
            Number of rows updated.
        """
        return await self.increment(column, -amount, **extra)

    @classmethod
    async def raw(cls, model_class: type[Model], sql: str, params: list | None = None) -> list:
        """Execute raw SQL and return model instances.

        Args:
            model_class: The Model subclass to instantiate from rows.
            sql: Raw SQL SELECT statement.
            params: Optional parameter list.

        Returns:
            List of model instances created from the result rows.
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        rows = await backend.fetch_all(sql, params or [])
        return [model_class._from_row(dict(r) if not isinstance(r, dict) else r) for r in rows]

    async def chunk(self, size: int, callback: Any) -> None:
        """Process results in chunks to avoid loading everything into RAM.

        The callback can be either sync or async. The builder's limit/offset
        state is preserved after chunking completes.

        Args:
            size: Number of records per chunk.
            callback: Callable receiving each chunk (list of instances).
        """
        saved_limit, saved_offset = self._limit_val, self._offset_val
        offset = 0
        try:
            while True:
                self._limit_val = size
                self._offset_val = offset
                results = await self.get()
                if not results:
                    break
                result = callback(results)
                if inspect.isawaitable(result):
                    await result
                if len(results) < size:
                    break
                offset += size
        finally:
            self._limit_val, self._offset_val = saved_limit, saved_offset

    def _log_query(self, sql: str, params: list) -> None:
        """Log the query if debug mode is enabled.

        Args:
            sql: The SQL string executed.
            params: The parameter list used.
        """
        if self._debug:
            self._query_log.append((sql, list(params)))
