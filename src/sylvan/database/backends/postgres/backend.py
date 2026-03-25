"""PostgreSQL storage backend — async via asyncpg with connection pooling.

Requires: ``pip install sylvan[postgres]`` (asyncpg + pgvector extensions).
"""

from typing import Any

from sylvan.database.backends.base import BaseBackend
from sylvan.database.backends.postgres.dialect import PostgresDialect
from sylvan.logging import get_logger

logger = get_logger(__name__)


class PostgresBackend(BaseBackend):
    """Async PostgreSQL backend using asyncpg with connection pooling.

    Supports pgvector for vector similarity search and GIN-indexed
    tsvector columns for full-text search.

    Attributes:
        dsn: PostgreSQL connection string.
        dialect: The PostgreSQL SQL dialect instance.
        min_pool_size: Minimum connections in the pool.
        max_pool_size: Maximum connections in the pool.
    """

    def __init__(
        self,
        dsn: str,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ) -> None:
        """Initialize the PostgreSQL backend.

        Args:
            dsn: Connection string (e.g., ``postgresql://user:pass@host/db``).
            min_pool_size: Minimum number of connections to maintain.
            max_pool_size: Maximum number of connections allowed.
        """
        self.dsn = dsn
        self.dialect = PostgresDialect()
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self._pool = None

    async def connect(self) -> None:
        """Create the connection pool and verify pgvector is available."""
        try:
            import asyncpg
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PostgreSQL support. Install with: pip install sylvan[postgres]"
            ) from exc

        self._pool = await asyncpg.create_pool(
            self.dsn,
            min_size=self.min_pool_size,
            max_size=self.max_pool_size,
        )

        async with self._pool.acquire() as conn:
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                logger.debug("pgvector_extension_ready")
            except Exception as error:
                logger.warning("pgvector_extension_failed", error=str(error))

        logger.info("postgres_backend_ready", dsn=self.dsn.split("@")[-1])

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> Any:
        """Get the active connection pool.

        Returns:
            The asyncpg connection pool.

        Raises:
            RuntimeError: If the backend is not connected.
        """
        if self._pool is None:
            raise RuntimeError("PostgresBackend is not connected. Call connect() first.")
        return self._pool

    @property
    def max_connections(self) -> int:
        """Return the maximum pool size.

        Returns:
            The configured maximum connection count.
        """
        return self.max_pool_size

    async def execute(self, sql: str, params: list[Any] | None = None) -> int:
        """Execute a write statement.

        Args:
            sql: SQL statement with $N placeholders.
            params: Bind parameters.

        Returns:
            Number of rows affected.
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(sql, *(params or []))
            count_str = result.split()[-1] if result else "0"
            try:
                return int(count_str)
            except ValueError:
                return 0

    async def execute_returning_id(self, sql: str, params: list[Any] | None = None) -> int | None:
        """Execute an INSERT and return the generated row ID.

        Appends RETURNING id to the SQL if not already present.

        Args:
            sql: INSERT SQL statement with $N placeholders.
            params: Bind parameters.

        Returns:
            The auto-generated row ID, or None.
        """
        if "RETURNING" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, *(params or []))
            return row[0] if row else None

    async def fetch_one(self, sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
        """Fetch a single row as a dict.

        Args:
            sql: SELECT SQL statement.
            params: Bind parameters.

        Returns:
            Row as a dict, or None.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, *(params or []))
            return dict(row) if row else None

    async def fetch_all(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Fetch all matching rows as dicts.

        Args:
            sql: SELECT SQL statement.
            params: Bind parameters.

        Returns:
            List of rows as dicts.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *(params or []))
            return [dict(row) for row in rows]

    async def fetch_value(self, sql: str, params: list[Any] | None = None) -> Any:
        """Fetch a single scalar value.

        Args:
            sql: SELECT SQL statement returning one column.
            params: Bind parameters.

        Returns:
            The scalar value, or None.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(sql, *(params or []))

    async def commit(self) -> None:
        """No-op for PostgreSQL — asyncpg auto-commits by default.

        For explicit transactions, use ``async with backend.transaction()``.
        """

    async def rollback(self) -> None:
        """No-op for PostgreSQL — transaction rollback is handled by the pool."""

    async def ensure_schema(self, ddl: str) -> None:
        """Execute DDL statements.

        Args:
            ddl: SQL DDL to execute (may contain multiple statements).
        """
        async with self.pool.acquire() as conn:
            await conn.execute(ddl)

    async def table_exists(self, table_name: str) -> bool:
        """Check whether a table exists using information_schema.

        Args:
            table_name: Table name to check.

        Returns:
            True if the table exists.
        """
        result = await self.fetch_value(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
            [table_name],
        )
        return bool(result)
