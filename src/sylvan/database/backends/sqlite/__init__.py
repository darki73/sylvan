"""SQLite backend — aiosqlite + FTS5 + sqlite-vec."""

from sylvan.database.backends.sqlite.backend import SQLiteBackend
from sylvan.database.backends.sqlite.dialect import SQLiteDialect

__all__ = ["SQLiteBackend", "SQLiteDialect"]
