"""PostgreSQL SQL dialect — generates PostgreSQL-specific SQL.

Uses numbered $1/$2/$3 placeholders, tsvector/GIN for full-text search,
and pgvector for vector similarity search.
"""

from typing import Any

from sylvan.logging import get_logger

logger = get_logger(__name__)


class PostgresDialect:
    """SQL dialect for PostgreSQL.

    Handles PostgreSQL-specific syntax: numbered $N placeholders,
    tsvector @@ to_tsquery for FTS, pgvector <-> distance operator
    for vector search, INSERT ... ON CONFLICT.

    Attributes:
        name: The dialect identifier.
    """

    name: str = "postgres"

    @property
    def placeholder(self) -> str:
        """Return the PostgreSQL placeholder style indicator.

        PostgreSQL uses numbered placeholders ($1, $2, etc.), not
        positional '?'. This returns '$' as a signal to the ORM
        that numbered placeholders are needed.

        Returns:
            The '$' character indicating numbered placeholders.
        """
        return "$"

    def placeholder_for(self, index: int) -> str:
        """Generate a numbered placeholder for the Nth parameter.

        Args:
            index: Zero-based parameter index.

        Returns:
            Numbered placeholder like '$1', '$2', etc.
        """
        return f"${index + 1}"

    def placeholders(self, count: int) -> str:
        """Generate a comma-separated list of numbered placeholders.

        Args:
            count: Number of placeholders needed.

        Returns:
            String like '$1, $2, $3' for the given count.
        """
        return ", ".join(self.placeholder_for(i) for i in range(count))

    def build_upsert(
        self,
        table: str,
        columns: list[str],
        conflict_columns: list[str],
        update_columns: list[str],
    ) -> str:
        """Generate PostgreSQL INSERT ... ON CONFLICT DO UPDATE statement.

        Uses numbered placeholders for all values.

        Args:
            table: Table name.
            columns: All columns being inserted.
            conflict_columns: Columns that trigger the conflict.
            update_columns: Columns to update on conflict.

        Returns:
            Complete INSERT ... ON CONFLICT SQL with numbered placeholders.
        """
        cols_str = ", ".join(columns)
        placeholders = self.placeholders(len(columns))
        conflict_str = ", ".join(conflict_columns)

        if update_columns:
            update_str = ", ".join(f"{col}=EXCLUDED.{col}" for col in update_columns)
            return (
                f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_str}) DO UPDATE SET {update_str}"
            )
        return (
            f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_str}) DO NOTHING"
        )

    def build_insert_or_ignore(self, table: str, columns: list[str]) -> str:
        """Generate INSERT ... ON CONFLICT DO NOTHING statement.

        Args:
            table: Table name.
            columns: Columns being inserted.

        Returns:
            Complete SQL with numbered placeholders.
        """
        cols_str = ", ".join(columns)
        placeholders = self.placeholders(len(columns))
        return f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    def build_fts_search(
        self,
        table: str,
        fts_table: str,
        query: str,
        select_columns: list[str],
        weights: str | None = None,
    ) -> tuple[str, list[Any]]:
        """Generate PostgreSQL full-text search query using tsvector/GIN.

        Uses ``to_tsvector()`` and ``to_tsquery()`` with ``ts_rank()``
        for relevance scoring. The FTS index is on the same table
        (not a separate virtual table like SQLite FTS5).

        Args:
            table: The data table with tsvector columns.
            fts_table: Ignored for PostgreSQL (FTS is on the main table).
                Kept for interface compatibility with the Dialect protocol.
            query: The search query string.
            select_columns: Columns to select.
            weights: Column weight configuration (PostgreSQL uses
                setweight() at index time, not query time).

        Returns:
            Tuple of (SQL string, bind parameters).
        """
        cols = ", ".join(f"{table}.{col}" for col in select_columns)
        tsquery = " & ".join(query.split())

        sql = (
            f"SELECT {cols}, "
            f"ts_rank(search_vector, to_tsquery('english', $1)) AS _rank "
            f"FROM {table} "
            f"WHERE search_vector @@ to_tsquery('english', $1) "
            f"ORDER BY _rank DESC"
        )
        return sql, [tsquery]

    def build_vector_search(
        self,
        table: str,
        vec_table: str,
        vec_column: str,
        vector: list[float],
        k: int,
        select_columns: list[str],
    ) -> tuple[str, list[Any]]:
        """Generate pgvector similarity search query.

        Uses the ``<->`` L2 distance operator for nearest neighbor search.
        The vector is passed as a pgvector-compatible string format.

        Args:
            table: The main data table.
            vec_table: The table containing vector embeddings.
            vec_column: The join column between main and vector tables.
            vector: The query vector as a list of floats.
            k: Number of nearest neighbors to return.
            select_columns: Columns to select from the main table.

        Returns:
            Tuple of (SQL string, bind parameters).
        """
        cols = ", ".join(f"{table}.{col}" for col in select_columns)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"

        sql = (
            f"SELECT {cols}, "
            f"embedding <-> $1::vector AS distance "
            f"FROM {vec_table} "
            f"JOIN {table} ON {table}.{vec_column} = {vec_table}.{vec_column} "
            f"ORDER BY distance "
            f"LIMIT $2"
        )
        return sql, [vec_str, k]
