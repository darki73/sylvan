"""SQL building mixin for QueryBuilder.

Handles WHERE clause construction, main SQL generation, and FTS SQL generation.
All methods are synchronous — they build SQL strings without touching the database.
SQL is generated through the backend's Dialect for database portability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder


class QuerySqlMixin:
    """Mixin providing SQL building internals for QueryBuilder."""

    self: QueryBuilder

    def _get_all_wheres(self) -> list[tuple[str, list, str]]:
        """Return the accumulated wheres list.

        Returns:
            List of (clause, params, connector) tuples.
        """
        return list(self._wheres)

    def _build_where(self) -> tuple[str, list]:
        """Build the WHERE clause string and params from accumulated wheres.

        Returns:
            Tuple of (where SQL string, parameter list).
        """
        wheres = self._get_all_wheres()

        if not wheres:
            return "", []
        all_params: list[Any] = []
        parts: list[str] = []
        for i, (clause, params, connector) in enumerate(wheres):
            if i > 0:
                parts.append(f" {connector} {clause}")
            else:
                parts.append(clause)
            all_params.extend(params)
        return "".join(parts), all_params

    def _get_dialect(self):
        """Get the SQL dialect from the backend.

        Returns:
            The Dialect instance for database-specific SQL generation.
        """
        return self.backend.dialect

    def _translate_placeholders(self, sql: str) -> str:
        """Replace internal '?' placeholders with dialect-specific ones.

        SQLite uses '?' (no-op). PostgreSQL uses numbered '$1', '$2', etc.
        Called as the final step before returning any generated SQL.

        Args:
            sql: SQL string with '?' placeholders.

        Returns:
            SQL string with dialect-appropriate placeholders.
        """
        dialect = self._get_dialect()
        if dialect.placeholder == "?":
            return sql
        parts = sql.split("?")
        if len(parts) == 1:
            return sql
        result = parts[0]
        for i, part in enumerate(parts[1:]):
            result += dialect.placeholder_for(i) + part
        return result

    def _build_sql(self, select_override: str | None = None) -> tuple[str, list]:
        """Build the full SELECT SQL statement and params.

        Args:
            select_override: Optional replacement for the SELECT columns expression.

        Returns:
            Tuple of (complete SQL string, parameter list).
        """
        table = self._model.__table__

        if self._fts_query:
            return self._build_fts_sql(select_override)

        if select_override:
            select = select_override
        else:
            select_parts: list[str] = []
            if self._selects:
                select_parts.extend(self._selects)
            else:
                select_parts.append(f"{table}.*")
            select_parts.extend(self._select_raws)
            select = ", ".join(select_parts)

        sql = f"SELECT {select} FROM {table}"

        for j in self._joins:
            sql += f" {j}"

        where_sql, params = self._build_where()
        if where_sql:
            sql += f" WHERE {where_sql}"

        if self._group_bys:
            sql += f" GROUP BY {', '.join(self._group_bys)}"
        if self._having:
            having_clauses = []
            for h_clause, h_params in self._having:
                having_clauses.append(h_clause)
                params.extend(h_params)
            sql += f" HAVING {' AND '.join(having_clauses)}"
        if self._order_bys:
            sql += f" ORDER BY {', '.join(self._order_bys)}"
        if self._limit_val is not None:
            sql += " LIMIT ?"
            params.append(self._limit_val)
        if self._offset_val is not None:
            sql += " OFFSET ?"
            params.append(self._offset_val)

        return self._translate_placeholders(sql), params

    def _build_fts_sql(self, select_override: str | None = None) -> tuple[str, list]:
        """Build full-text search SQL using the dialect.

        Delegates the FTS-specific syntax (MATCH vs @@, BM25 ranking) to
        the dialect, then appends additional JOINs, WHERE clauses, ORDER BY,
        and LIMIT from the query builder.

        Args:
            select_override: Optional replacement for the SELECT columns expression.

        Returns:
            Tuple of (FTS SQL string, parameter list).
        """
        table = self._model.__table__
        fts = self._model.__fts_table__
        weights = getattr(self._model, "__fts_weights__", None)
        dialect = self._get_dialect()

        select_columns = ["*"] if not self._selects else self._selects
        base_sql, params = dialect.build_fts_search(
            table=table,
            fts_table=fts,
            query=self._fts_query,
            select_columns=select_columns,
            weights=weights,
        )

        if select_override:
            base_sql = base_sql.replace(
                base_sql[base_sql.index("SELECT") + 7 : base_sql.index("FROM")].strip(),
                select_override,
                1,
            )

        for j in self._joins:
            insert_pos = base_sql.index(" WHERE")
            base_sql = base_sql[:insert_pos] + f" {j}" + base_sql[insert_pos:]

        for clause, clause_params, connector in self._get_all_wheres():
            where_pos = base_sql.index("ORDER BY") if "ORDER BY" in base_sql else len(base_sql)
            base_sql = base_sql[:where_pos] + f" {connector} {clause} " + base_sql[where_pos:]
            params.extend(clause_params)

        if self._order_bys:
            if "ORDER BY" in base_sql:
                order_start = base_sql.index("ORDER BY")
                base_sql = base_sql[:order_start] + f"ORDER BY {', '.join(self._order_bys)}"
            else:
                base_sql += f" ORDER BY {', '.join(self._order_bys)}"

        if self._group_bys:
            if "ORDER BY" in base_sql:
                group_pos = base_sql.index("ORDER BY")
            else:
                group_pos = len(base_sql)
            base_sql = base_sql[:group_pos] + f"GROUP BY {', '.join(self._group_bys)} " + base_sql[group_pos:]

        if self._having:
            having_clauses = []
            for h_clause, h_params in self._having:
                having_clauses.append(h_clause)
                params.extend(h_params)
            if "ORDER BY" in base_sql:
                having_pos = base_sql.index("ORDER BY")
            else:
                having_pos = len(base_sql)
            base_sql = base_sql[:having_pos] + f"HAVING {' AND '.join(having_clauses)} " + base_sql[having_pos:]

        if self._limit_val is not None:
            base_sql += " LIMIT ?"
            params.append(self._limit_val)
        if self._offset_val is not None:
            base_sql += " OFFSET ?"
            params.append(self._offset_val)

        return self._translate_placeholders(base_sql), params
