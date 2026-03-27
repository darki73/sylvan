"""SQLite storage backend -- async wrapper around aiosqlite with extensions."""

from pathlib import Path
from typing import Any

import aiosqlite

from sylvan.database.backends.base import BaseBackend
from sylvan.database.backends.sqlite.dialect import SQLiteDialect
from sylvan.logging import get_logger

logger = get_logger(__name__)


def _load_sqlite_vec(conn: object) -> None:
    """Load sqlite-vec extension inside aiosqlite's background thread."""
    import contextlib

    import sqlite_vec

    with contextlib.suppress(AttributeError):
        conn.enable_load_extension(True)
    sqlite_vec.load(conn)


async def _open_connection(db_path: str, *, readonly: bool = False) -> aiosqlite.Connection:
    """Open and configure an aiosqlite connection.

    Args:
        db_path: Path to the SQLite database file.
        readonly: If True, open in read-only mode via URI.

    Returns:
        A configured aiosqlite connection.
    """
    if readonly:
        uri = f"file:{db_path}?mode=ro"
        conn = await aiosqlite.connect(uri, uri=True)
    else:
        conn = await aiosqlite.connect(db_path)

    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=OFF")

    try:
        await conn._execute(_load_sqlite_vec, conn._connection)
        logger.debug("sqlite_vec_loaded", readonly=readonly)
    except Exception as error:
        logger.warning("sqlite_vec_load_failed", error=str(error), readonly=readonly)

    return conn


class SQLiteBackend(BaseBackend):
    """Async SQLite backend with dual connections for cluster support.

    Opens two connections to the same WAL-mode database:
    - **Write connection**: handles INSERT/UPDATE/DELETE/DDL and commits
    - **Read connection**: handles all SELECT queries (read-only)

    Both connections see the same data because WAL mode allows concurrent
    readers alongside a single writer. On follower promotion, the write
    connection is already open and warm.

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
        self._read_connection: aiosqlite.Connection | None = None
        self._follower_mode: bool = False

    async def connect(self) -> None:
        """Open a write connection for initial setup (migrations).

        After role discovery, call ``enable_follower_mode()`` to close
        the write connection and switch to read-only, or keep it for
        the leader.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db_str = str(self.db_path)
        self._connection = await _open_connection(db_str, readonly=False)
        self._read_connection = await _open_connection(db_str, readonly=True)

    async def enable_leader_mode(self) -> None:
        """Finalize as leader, keeping both connections open.

        The write connection stays active for all DB mutations.
        Reads go through the write connection for consistency.
        """
        self._follower_mode = False
        logger.debug("leader_mode_enabled")

    async def enable_follower_mode(self) -> None:
        """Finalize as follower by closing the write connection.

        After this, only the read-only connection remains. Any write
        attempt will raise RuntimeError. Call ``promote_to_leader()``
        to reopen the write connection if this node becomes leader.
        """
        if self._connection is not None:
            import contextlib

            with contextlib.suppress(Exception):
                await self._connection.close()
            self._connection = None

        self._follower_mode = True
        logger.debug("follower_mode_enabled")

    async def promote_to_leader(self) -> None:
        """Reopen the write connection for a follower becoming leader.

        Idempotent - returns immediately if the write connection is
        already open.
        """
        if self._connection is not None:
            return
        db_str = str(self.db_path)
        self._connection = await _open_connection(db_str, readonly=False)
        self._follower_mode = False
        logger.debug("promoted_to_writer")

    async def disconnect(self) -> None:
        """Close all open connections.

        Checkpoints WAL on the write connection if available.
        """
        import contextlib

        if self._connection is not None:
            with contextlib.suppress(Exception):
                await self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._connection.close()
            self._connection = None

        if self._read_connection is not None:
            await self._read_connection.close()
            self._read_connection = None

    @property
    def connection(self) -> aiosqlite.Connection:
        """Get the write connection.

        Returns:
            The aiosqlite write connection.

        Raises:
            RuntimeError: If the backend is not connected.
        """
        if self._connection is None:
            raise RuntimeError("SQLiteBackend is not connected. Call connect() first.")
        return self._connection

    @property
    def reader(self) -> aiosqlite.Connection:
        """Get the appropriate connection for reads.

        In follower mode, uses the dedicated read-only connection so
        the follower never accidentally writes. In leader/standalone
        mode, uses the write connection so reads see uncommitted writes
        within the same session.

        Returns:
            The aiosqlite connection for read operations.
        """
        if self._follower_mode and self._read_connection is not None:
            return self._read_connection
        return self.connection

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
        """Fetch a single row as a dict (uses read connection).

        Args:
            sql: SELECT SQL statement.
            params: Bind parameters.

        Returns:
            Row as a dict, or None.
        """
        cursor = await self.reader.execute(sql, params or [])
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetch_all(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Fetch all matching rows as dicts (uses read connection).

        Args:
            sql: SELECT SQL statement.
            params: Bind parameters.

        Returns:
            List of rows as dicts.
        """
        cursor = await self.reader.execute(sql, params or [])
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def fetch_value(self, sql: str, params: list[Any] | None = None) -> Any:
        """Fetch a single scalar value (uses read connection).

        Args:
            sql: SELECT SQL statement returning one column.
            params: Bind parameters.

        Returns:
            The scalar value, or None.
        """
        cursor = await self.reader.execute(sql, params or [])
        row = await cursor.fetchone()
        if row is None:
            return None
        return row[0]

    async def commit(self) -> None:
        """Commit the current transaction on the write connection."""
        await self.connection.commit()

    async def rollback(self) -> None:
        """Roll back the current transaction on the write connection."""
        await self.connection.rollback()

    async def ensure_schema(self, ddl: str) -> None:
        """Execute DDL statements on the write connection.

        Args:
            ddl: SQL DDL to execute (may contain multiple statements).
        """
        await self.connection.executescript(ddl)

    @property
    def max_connections(self) -> int:
        """Number of connections this backend maintains.

        Returns:
            2 (one writer, one reader).
        """
        return 2

    async def table_exists(self, table_name: str) -> bool:
        """Check whether a table exists (uses read connection).

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
