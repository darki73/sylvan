"""Search mixin for QueryBuilder.

Full-text search and vector similarity search, delegated to the
backend's Dialect for database-specific SQL generation.
All execution methods are async.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from sylvan.database.orm.runtime.search_helpers import (
    embed_text,
    prepare_fts_query,
    reciprocal_rank_fusion,
)

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder

T = TypeVar("T")


class QuerySearchMixin:
    """Mixin providing FTS and vector search methods for QueryBuilder."""

    self: QueryBuilder

    def search(self: QueryBuilder[T], query: str) -> QueryBuilder[T]:
        """Add full-text search to this query.

        The actual FTS syntax (MATCH, @@, etc.) is handled by the dialect.

        Args:
            query: The search terms.

        Returns:
            This builder for chaining.
        """
        self._fts_query = prepare_fts_query(query)
        return self

    def similar_to(
        self: QueryBuilder[T], text_or_vector: str | list[float], k: int = 20, weight: float = 0.3
    ) -> QueryBuilder[T]:
        """Add vector similarity search.

        The actual vector query syntax is handled by the dialect.

        Args:
            text_or_vector: Text string (will be embedded) or raw float vector.
            k: Number of nearest neighbors to retrieve.
            weight: Vector weight in hybrid search (0-1).

        Returns:
            This builder for chaining.
        """
        if isinstance(text_or_vector, str):
            self._vec_text = text_or_vector
        else:
            self._vec_vector = text_or_vector
        self._vec_k = k
        self._vec_weight = weight
        return self

    async def _execute_vector(self) -> list:
        """Execute a pure vector similarity search via the dialect.

        Returns:
            List of model instances ordered by vector distance.
        """
        vec_table = self._model.__vec_table__
        vec_col = self._model.__vec_column__
        table = self._model.__table__
        dialect = self.backend.dialect

        query_vec = self._resolve_query_vector()
        if query_vec is None:
            return []

        select_columns = self._selects if self._selects else ["*"]
        base_sql, params = dialect.build_vector_search(
            table=table,
            vec_table=vec_table,
            vec_column=vec_col,
            vector=query_vec,
            k=self._vec_k,
            select_columns=select_columns,
        )

        for j in self._joins:
            if "WHERE" in base_sql:
                insert_pos = base_sql.index(" WHERE")
                base_sql = base_sql[:insert_pos] + f" {j}" + base_sql[insert_pos:]
            else:
                base_sql += f" {j}"

        for clause, clause_params, connector in self._get_all_wheres():
            if "ORDER BY" in base_sql:
                order_pos = base_sql.index("ORDER BY")
                base_sql = base_sql[:order_pos] + f" {connector} {clause} " + base_sql[order_pos:]
            else:
                base_sql += f" {connector} {clause}"
            params.extend(clause_params)

        rows = await self.backend.fetch_all(self._translate_placeholders(base_sql), params)
        return [self._model._from_row(dict(r) if not isinstance(r, dict) else r) for r in rows]

    def _resolve_query_vector(self) -> list[float] | None:
        """Return the query vector, embedding text if necessary.

        Returns:
            A float vector, or None if no vector could be resolved.
        """
        if self._vec_vector is not None:
            return self._vec_vector
        if self._vec_text:
            return embed_text(self._vec_text)
        return None

    async def _execute_hybrid(self) -> list:
        """Execute hybrid FTS + vector search with RRF fusion.

        Returns:
            List of model instances ordered by fused relevance score.
        """
        from sylvan.database.orm.query.builder import QueryBuilder

        fts_builder = QueryBuilder(self._model)
        fts_builder._fts_query = self._fts_query
        fts_builder._wheres = list(self._wheres)
        fts_builder._joins = list(self._joins)
        fts_builder._join_set = set(self._join_set)
        fts_builder._order_bys = list(self._order_bys)
        fts_builder._group_bys = list(self._group_bys)
        fts_builder._having = list(self._having)
        fts_builder._selects = list(self._selects)
        fts_builder._select_raws = list(self._select_raws)
        fts_builder._limit_val = (self._limit_val or 20) * 2
        fts_sql, fts_params = fts_builder._build_fts_sql()
        fts_rows = await self.backend.fetch_all(fts_sql, fts_params)
        fts_results = [dict(r) if not isinstance(r, dict) else r for r in fts_rows]

        vec_results_raw = await self._execute_vector()
        vec_results = [r._to_dict() if hasattr(r, "_to_dict") else {} for r in vec_results_raw]

        if not fts_results and not vec_results:
            return []

        pk = self._model._pk_column
        fts_weight = 1.0 - self._vec_weight

        merged = reciprocal_rank_fusion(
            fts_results,
            vec_results,
            id_key=pk,
            fts_weight=fts_weight,
            vec_weight=self._vec_weight,
        )

        limit = self._limit_val or 20
        instances = [self._model._from_row(r) for r in merged[:limit]]

        if self._eager_loads:
            await self._load_eager(instances)

        return instances
