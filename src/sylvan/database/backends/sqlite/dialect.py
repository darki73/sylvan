"""SQLite SQL dialect — generates SQLite-specific SQL."""

from typing import Any


class SQLiteDialect:
    """SQL dialect for SQLite.

    Handles SQLite-specific syntax: '?' placeholders, FTS5 MATCH queries,
    sqlite-vec distance functions, INSERT OR IGNORE, ON CONFLICT.

    Attributes:
        name: The dialect identifier.
    """

    name: str = "sqlite"

    @property
    def placeholder(self) -> str:
        """Return the SQLite parameter placeholder.

        Returns:
            The '?' character used by SQLite.
        """
        return "?"

    def placeholder_for(self, index: int) -> str:
        """Generate a placeholder for the Nth parameter.

        SQLite uses positional '?' for all parameters.

        Args:
            index: Zero-based parameter index (ignored for SQLite).

        Returns:
            The '?' placeholder.
        """
        return "?"

    def placeholders(self, count: int) -> str:
        """Generate a comma-separated list of placeholders.

        Args:
            count: Number of placeholders needed.

        Returns:
            String like '?, ?, ?' for the given count.
        """
        return ", ".join("?" for _ in range(count))

    def build_upsert(
        self,
        table: str,
        columns: list[str],
        conflict_columns: list[str],
        update_columns: list[str],
    ) -> str:
        """Generate SQLite ON CONFLICT DO UPDATE statement.

        Args:
            table: Table name.
            columns: All columns being inserted.
            conflict_columns: Columns that trigger the conflict.
            update_columns: Columns to update on conflict.

        Returns:
            Complete INSERT ... ON CONFLICT DO UPDATE SQL.
        """
        cols_str = ", ".join(columns)
        placeholders = self.placeholders(len(columns))
        conflict_str = ", ".join(conflict_columns)

        if update_columns:
            update_str = ", ".join(f"{col}=excluded.{col}" for col in update_columns)
            return (
                f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) "
                f"ON CONFLICT({conflict_str}) DO UPDATE SET {update_str}"
            )
        return f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT({conflict_str}) DO NOTHING"

    def build_insert_or_ignore(self, table: str, columns: list[str]) -> str:
        """Generate SQLite INSERT OR IGNORE statement.

        Args:
            table: Table name.
            columns: Columns being inserted.

        Returns:
            Complete INSERT OR IGNORE SQL.
        """
        cols_str = ", ".join(columns)
        placeholders = self.placeholders(len(columns))
        return f"INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({placeholders})"

    def build_fts_search(
        self,
        table: str,
        fts_table: str,
        query: str,
        select_columns: list[str],
        weights: str | None = None,
    ) -> tuple[str, list[Any]]:
        """Generate SQLite FTS5 search query with BM25 ranking.

        Args:
            table: The main data table (e.g., 'symbols').
            fts_table: The FTS5 virtual table (e.g., 'symbols_fts').
            query: The search query string.
            select_columns: Columns to select from the main table.
            weights: BM25 weight string for column ranking.

        Returns:
            Tuple of (SQL, params) for the FTS5 search.
        """
        cols = ", ".join(f"{table}.{col}" for col in select_columns)
        rank_expr = f"bm25({fts_table}, {weights})" if weights else f"bm25({fts_table})"

        sql = (
            f"SELECT {cols}, {rank_expr} AS _rank "
            f"FROM {fts_table} "
            f"JOIN {table} ON {table}.id = {fts_table}.rowid "
            f"WHERE {fts_table} MATCH ? "
            f"ORDER BY _rank"
        )
        return sql, [query]

    def build_vector_search(
        self,
        table: str,
        vec_table: str,
        vec_column: str,
        vector: list[float],
        k: int,
        select_columns: list[str],
    ) -> tuple[str, list[Any]]:
        """Generate sqlite-vec vector similarity search query.

        Args:
            table: The main data table.
            vec_table: The sqlite-vec virtual table.
            vec_column: The join column (e.g., 'symbol_id').
            vector: The query vector as a list of floats.
            k: Number of nearest neighbors to return.
            select_columns: Columns to select from the main table.

        Returns:
            Tuple of (SQL, params) for the vector search.
        """
        from sylvan.database.orm.runtime.search_helpers import vec_to_blob

        cols = ", ".join(f"{table}.{col}" for col in select_columns)
        blob = vec_to_blob(vector)

        sql = (
            f"SELECT {cols}, distance "
            f"FROM {vec_table} "
            f"JOIN {table} ON {table}.{vec_column} = {vec_table}.{vec_column} "
            f"WHERE embedding MATCH ? AND k = ? "
            f"ORDER BY distance"
        )
        return sql, [blob, k]
