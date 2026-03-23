"""SQLite storage backend — async wrapper around aiosqlite with extensions."""

from pathlib import Path
from typing import Any

import aiosqlite

from sylvan.database.backends.base import BaseBackend
from sylvan.database.backends.sqlite.dialect import SQLiteDialect
from sylvan.logging import get_logger

logger = get_logger(__name__)


class SQLiteBackend(BaseBackend):
    """Async SQLite backend using aiosqlite.

    Configures WAL mode, loads the sqlite-vec extension, and provides
    async query execution. Designed for single-process, multi-thread
    use with one connection per backend instance.

    Attributes:
        db_path: Path to the SQLite database file.
        dialect: The SQLite SQL dialect instance.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the SQLite backend.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.dialect = SQLiteDialect()
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and configure SQLite settings.

        Enables WAL journal mode, sets busy timeout, loads sqlite-vec,
        and configures row_factory for dict-style row access.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(str(self.db_path))
        self._connection.row_factory = aiosqlite.Row

        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA busy_timeout=5000")
        await self._connection.execute("PRAGMA foreign_keys=OFF")

        try:
            import sqlite_vec

            def _load_vec_extension(conn: object) -> None:
                """Load sqlite-vec inside aiosqlite's background thread."""
                conn.enable_load_extension(True)
                sqlite_vec.load(conn)

            await self._connection._execute(_load_vec_extension, self._connection._connection)
            logger.debug("sqlite_vec_loaded")
        except Exception as error:
            logger.warning("sqlite_vec_load_failed", error=str(error))

    async def disconnect(self) -> None:
        """Close the database connection and clean up WAL/SHM files.

        Checkpoints the WAL into the main database before closing so
        that SQLite removes the WAL and SHM files on last connection close.
        """
        if self._connection is not None:
            import contextlib
            with contextlib.suppress(Exception):
                await self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> aiosqlite.Connection:
        """Get the active connection.

        Returns:
            The aiosqlite connection.

        Raises:
            RuntimeError: If the backend is not connected.
        """
        if self._connection is None:
            raise RuntimeError("SQLiteBackend is not connected. Call connect() first.")
        return self._connection

    async def execute(self, sql: str, params: list[Any] | None = None) -> int:
        """Execute a write statement.

        Args:
            sql: SQL statement.
            params: Bind parameters.

        Returns:
            Number of rows affected.
        """
        cursor = await self.connection.execute(sql, params or [])
        return cursor.rowcount

    async def execute_returning_id(self, sql: str, params: list[Any] | None = None) -> int | None:
        """Execute an INSERT and return the generated row ID.

        Args:
            sql: INSERT SQL statement.
            params: Bind parameters.

        Returns:
            The lastrowid from the cursor.
        """
        cursor = await self.connection.execute(sql, params or [])
        return cursor.lastrowid

    async def fetch_one(self, sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
        """Fetch a single row as a dict.

        Args:
            sql: SELECT SQL statement.
            params: Bind parameters.

        Returns:
            Row as a dict, or None.
        """
        cursor = await self.connection.execute(sql, params or [])
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetch_all(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Fetch all matching rows as dicts.

        Args:
            sql: SELECT SQL statement.
            params: Bind parameters.

        Returns:
            List of rows as dicts.
        """
        cursor = await self.connection.execute(sql, params or [])
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def fetch_value(self, sql: str, params: list[Any] | None = None) -> Any:
        """Fetch a single scalar value.

        Args:
            sql: SELECT SQL statement returning one column.
            params: Bind parameters.

        Returns:
            The scalar value, or None.
        """
        cursor = await self.connection.execute(sql, params or [])
        row = await cursor.fetchone()
        if row is None:
            return None
        return row[0]

    async def commit(self) -> None:
        """Commit the current transaction.

        WAL checkpoint happens at disconnect, not per-commit — avoids
        unnecessary I/O overhead during bulk operations like indexing.
        """
        await self.connection.commit()

    async def rollback(self) -> None:
        """Roll back the current transaction.
        """
        await self.connection.rollback()

    async def ensure_schema(self, ddl: str) -> None:
        """Execute DDL statements.

        Args:
            ddl: SQL DDL to execute (may contain multiple statements).
        """
        await self.connection.executescript(ddl)

    @property
    def max_connections(self) -> int:
        """SQLite supports a single writer connection.

        Returns:
            Always 1 for SQLite.
        """
        return 1

    async def table_exists(self, table_name: str) -> bool:
        """Check whether a table exists.

        Args:
            table_name: Table name to check.

        Returns:
            True if the table exists.
        """
        result = await self.fetch_value(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
            [table_name],
        )
        return bool(result and result > 0)
