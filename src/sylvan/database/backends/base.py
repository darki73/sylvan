"""Storage backend protocol — the contract every database backend must fulfill."""

from collections.abc import AsyncIterator, ItemsView, KeysView, ValuesView
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True, frozen=True)
class QueryResult:
    """A single row returned from a query.

    Attributes:
        data: Dict mapping column names to values.
    """

    data: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        """Access a column value by name.

        Args:
            key: Column name.

        Returns:
            The column value.
        """
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Access a column value with a default.

        Args:
            key: Column name.
            default: Value to return if key is missing.

        Returns:
            The column value, or default.
        """
        return self.data.get(key, default)

    def keys(self) -> KeysView[str]:
        """Return column names.

        Returns:
            Dict keys view of column names.
        """
        return self.data.keys()

    def values(self) -> ValuesView[Any]:
        """Return column values.

        Returns:
            Dict values view of column values.
        """
        return self.data.values()

    def items(self) -> ItemsView[str, Any]:
        """Return column name-value pairs.

        Returns:
            Dict items view of (name, value) pairs.
        """
        return self.data.items()


@runtime_checkable
class StorageBackend(Protocol):
    """Contract that every database backend must fulfill.

    Every backend must implement async methods for executing queries,
    managing transactions, and handling full-text and vector search.
    The ORM calls these methods — it never generates SQL directly.
    """

    async def connect(self) -> None:
        """Establish the database connection.
        """
        ...

    async def disconnect(self) -> None:
        """Close the database connection.
        """
        ...

    async def execute(self, sql: str, params: list[Any] | None = None) -> int:
        """Execute a write statement (INSERT, UPDATE, DELETE).

        Args:
            sql: The SQL statement.
            params: Bind parameters.

        Returns:
            Number of rows affected.
        """
        ...

    async def execute_returning_id(self, sql: str, params: list[Any] | None = None) -> int | None:
        """Execute an INSERT and return the generated row ID.

        Args:
            sql: The INSERT SQL statement.
            params: Bind parameters.

        Returns:
            The auto-generated row ID, or None if not applicable.
        """
        ...

    async def fetch_one(self, sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
        """Fetch a single row.

        Args:
            sql: The SELECT SQL statement.
            params: Bind parameters.

        Returns:
            Row as a dict, or None if no row matches.
        """
        ...

    async def fetch_all(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Fetch all matching rows.

        Args:
            sql: The SELECT SQL statement.
            params: Bind parameters.

        Returns:
            List of rows as dicts.
        """
        ...

    async def fetch_value(self, sql: str, params: list[Any] | None = None) -> Any:
        """Fetch a single scalar value.

        Args:
            sql: The SELECT SQL statement returning one column.
            params: Bind parameters.

        Returns:
            The scalar value, or None.
        """
        ...

    async def commit(self) -> None:
        """Commit the current transaction.
        """
        ...

    async def rollback(self) -> None:
        """Roll back the current transaction.
        """
        ...

    async def ensure_schema(self, ddl: str) -> None:
        """Execute DDL statements to ensure the schema exists.

        Args:
            ddl: The DDL SQL to execute.
        """
        ...

    async def table_exists(self, table_name: str) -> bool:
        """Check whether a table exists in the database.

        Args:
            table_name: Name of the table to check.

        Returns:
            True if the table exists.
        """
        ...

    @property
    def max_connections(self) -> int:
        """Maximum number of concurrent connections this backend supports.

        Returns:
            Connection pool size (1 for SQLite, configurable for PostgreSQL).
        """
        ...


class BaseBackend:
    """Shared behavior for all storage backends.

    Provides the transaction context manager.  Subclass this and
    implement the :class:`StorageBackend` protocol methods.

    Attributes:
        dialect: The SQL dialect for this backend, set by subclasses in __init__.
    """

    dialect: "Dialect"

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Async context manager for atomic transactions.

        Commits on successful exit, rolls back on exception.

        Yields:
            None.
        """
        try:
            yield
            await self.commit()  # type: ignore[attr-defined]
        except Exception:
            await self.rollback()  # type: ignore[attr-defined]
            raise


@runtime_checkable
class Dialect(Protocol):
    """Contract for database-specific SQL generation.

    Each backend has an associated dialect that knows how to generate
    the correct SQL syntax for that database engine.
    """

    @property
    def placeholder(self) -> str:
        """The parameter placeholder character.

        Returns:
            '?' for SQLite, '$' for PostgreSQL (numbered).
        """
        ...

    def placeholder_for(self, index: int) -> str:
        """Generate a placeholder for the Nth parameter.

        Args:
            index: Zero-based parameter index.

        Returns:
            The placeholder string (e.g., '?' or '$1').
        """
        ...

    def build_upsert(
        self,
        table: str,
        columns: list[str],
        conflict_columns: list[str],
        update_columns: list[str],
    ) -> str:
        """Generate an UPSERT (INSERT ... ON CONFLICT) statement.

        Args:
            table: Table name.
            columns: All columns being inserted.
            conflict_columns: Columns that trigger the conflict.
            update_columns: Columns to update on conflict.

        Returns:
            The complete SQL statement with placeholders.
        """
        ...

    def build_insert_or_ignore(self, table: str, columns: list[str]) -> str:
        """Generate an INSERT OR IGNORE / INSERT ... ON CONFLICT DO NOTHING.

        Args:
            table: Table name.
            columns: Columns being inserted.

        Returns:
            The complete SQL statement with placeholders.
        """
        ...

    def build_fts_search(
        self,
        table: str,
        fts_table: str,
        query: str,
        select_columns: list[str],
        weights: str | None = None,
    ) -> tuple[str, list[Any]]:
        """Generate a full-text search query.

        Args:
            table: The main data table.
            fts_table: The FTS index table.
            query: The search query string.
            select_columns: Columns to select.
            weights: BM25 weight string (dialect-specific).

        Returns:
            Tuple of (SQL string, bind parameters).
        """
        ...

    def build_vector_search(
        self,
        table: str,
        vec_table: str,
        vec_column: str,
        vector: list[float],
        k: int,
        select_columns: list[str],
    ) -> tuple[str, list[Any]]:
        """Generate a vector similarity search query.

        Args:
            table: The main data table.
            vec_table: The vector index table.
            vec_column: The join column in the vector table.
            vector: The query vector.
            k: Number of nearest neighbors.
            select_columns: Columns to select.

        Returns:
            Tuple of (SQL string, bind parameters).
        """
        ...
