"""Schema builder — the migration-facing API for DDL operations.

Provides a fluent, Laravel-style interface for creating, modifying, and
dropping tables, FTS5 virtual tables, sqlite-vec tables, triggers, and
indexes.  Compiles to SQL and executes against the storage backend.

Example::

    from sylvan.database.builder import Schema

    async def up(backend, dialect):
        schema = Schema(backend)

        await schema.create("repos", lambda t: (
            t.id(),
            t.text("name"),
            t.text("source_path").nullable().unique(),
            t.text("indexed_at"),
            t.text("repo_type").default("local"),
        ))

        await schema.create("files", lambda t: (
            t.id(),
            t.foreign_id("repo_id"),
            t.text("path"),
            t.text("language").nullable(),
            t.text("content_hash"),
            t.integer("byte_size"),
            t.real("mtime").nullable(),
            t.unique(["repo_id", "path"]),
        ))

        await schema.fts("symbols_fts",
            columns=["symbol_id", "name", "qualified_name", "signature",
                      "docstring", "summary", "keywords"],
            content_table="symbols",
        )

        await schema.vec("symbols_vec", id_column="symbol_id", dimensions=384)
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from sylvan.database.builder.blueprint import Blueprint, FtsTable, _validate_name

if TYPE_CHECKING:
    from collections.abc import Callable

    from sylvan.database.backends.base import StorageBackend


class Schema:
    """Fluent schema builder for migrations.

    Wraps a storage backend and provides high-level methods for DDL
    operations.  Can be used directly or as an async context manager.

    Args:
        backend: The async storage backend to execute SQL against.
    """

    def __init__(self, backend: StorageBackend) -> None:
        self._backend = backend

    async def __aenter__(self) -> Schema:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    async def create(self, table: str, callback: Callable[[Blueprint], object]) -> None:
        """Create a new table with columns and indexes.

        Args:
            table: Table name.
            callback: Receives a Blueprint; call methods to define columns/indexes.

        Example::

            await schema.create("repos", lambda t: (
                t.id(),
                t.text("name"),
                t.text("source_path").nullable().unique(),
            ))
        """
        bp = Blueprint(table)
        callback(bp)
        await self._backend.ensure_schema(bp.to_create_sql())
        for idx_sql in bp.to_index_sql():
            await self._backend.ensure_schema(idx_sql)

    async def create_quoted(self, table: str, callback: Callable[[Blueprint], object]) -> None:
        """Create a table whose name is a reserved word (quoted with double quotes).

        Args:
            table: Table name (will be quoted).
            callback: Receives a Blueprint.

        Example::

            await schema.create_quoted("references", lambda t: (...))
        """
        bp = Blueprint(f'"{table}"')
        callback(bp)
        await self._backend.ensure_schema(bp.to_create_sql())
        for idx_sql in bp.to_index_sql():
            await self._backend.ensure_schema(idx_sql)

    async def table(self, table: str, callback: Callable[[Blueprint], object]) -> None:
        """Modify an existing table — add columns and indexes.

        Args:
            table: Table name.
            callback: Receives a Blueprint; define new columns/indexes.

        Example::

            await schema.table("repos", lambda t: (
                t.text("description").nullable(),
                t.index("name"),
            ))
        """
        bp = Blueprint(table)
        callback(bp)
        for stmt in bp.to_alter_sql():
            await self._backend.execute(stmt)
        for idx_sql in bp.to_index_sql():
            await self._backend.ensure_schema(idx_sql)
        await self._backend.commit()

    async def drop(self, table: str) -> None:
        """Drop a table if it exists.

        Args:
            table: Table name.
        """
        _validate_name(table)
        await self._backend.execute(f"DROP TABLE IF EXISTS {table}")  # sylvan-sql-safe

    async def drop_quoted(self, table: str) -> None:
        """Drop a table whose name is a reserved word.

        Args:
            table: Table name (will be quoted).
        """
        _validate_name(table)
        await self._backend.execute(f'DROP TABLE IF EXISTS "{table}"')  # sylvan-sql-safe

    async def rename(self, old: str, new: str) -> None:
        """Rename a table.

        Args:
            old: Current table name.
            new: New table name.
        """
        _validate_name(old)
        _validate_name(new)
        await self._backend.execute(f"ALTER TABLE {old} RENAME TO {new}")  # sylvan-sql-safe

    async def rename_column(self, table: str, old: str, new: str) -> None:
        """Rename a column (SQLite 3.25+).

        Args:
            table: Table name.
            old: Current column name.
            new: New column name.
        """
        _validate_name(table)
        _validate_name(old)
        _validate_name(new)
        await self._backend.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")  # sylvan-sql-safe

    async def drop_column(self, table: str, column: str) -> None:
        """Drop a column (SQLite 3.35+).

        Args:
            table: Table name.
            column: Column to drop.
        """
        _validate_name(table)
        _validate_name(column)
        await self._backend.execute(f"ALTER TABLE {table} DROP COLUMN {column}")  # sylvan-sql-safe

    async def create_index(
        self,
        table: str,
        columns: list[str],
        *,
        name: str | None = None,
        unique: bool = False,
    ) -> None:
        """Create an index outside of a table blueprint.

        Args:
            table: Table the index belongs to.
            columns: Columns to index.
            name: Explicit index name (auto-generated if None).
            unique: Whether the index enforces uniqueness.
        """
        _validate_name(table)
        for col in columns:
            _validate_name(col)
        idx_name = name or f"idx_{table}_{'_'.join(columns)}"
        _validate_name(idx_name)
        unique_kw = "UNIQUE " if unique else ""
        cols = ", ".join(columns)
        await self._backend.ensure_schema(f"CREATE {unique_kw}INDEX IF NOT EXISTS {idx_name} ON {table}({cols})")

    async def create_index_quoted(
        self,
        table: str,
        columns: list[str],
        *,
        name: str | None = None,
    ) -> None:
        """Create an index on a quoted table name.

        Args:
            table: Table name (will be quoted).
            columns: Columns to index.
            name: Explicit index name (auto-generated if None).
        """
        _validate_name(table)
        for col in columns:
            _validate_name(col)
        idx_name = name or f"idx_{table}_{'_'.join(columns)}"
        _validate_name(idx_name)
        cols = ", ".join(columns)
        await self._backend.ensure_schema(f'CREATE INDEX IF NOT EXISTS {idx_name} ON "{table}"({cols})')

    async def drop_index(self, name: str) -> None:
        """Drop an index if it exists.

        Args:
            name: Index name.
        """
        _validate_name(name)
        await self._backend.execute(f"DROP INDEX IF EXISTS {name}")  # sylvan-sql-safe

    async def fts(
        self,
        name: str,
        *,
        columns: list[str],
        content_table: str,
        content_rowid: str = "id",
        tokenize: str = "porter unicode61",
    ) -> None:
        """Create an FTS5 virtual table with auto-sync triggers.

        Generates the virtual table and AFTER INSERT/DELETE/UPDATE triggers
        that keep the FTS index synchronized with the content table.

        Args:
            name: FTS table name (e.g., ``symbols_fts``).
            columns: Columns to include in the FTS index.
            content_table: Source table to sync from.
            content_rowid: Rowid column in the content table.
            tokenize: FTS5 tokenizer configuration.

        Example::

            await schema.fts("symbols_fts",
                columns=["symbol_id", "name", "qualified_name",
                         "signature", "docstring", "summary", "keywords"],
                content_table="symbols",
            )
        """
        fts_def = FtsTable(
            name=name,
            columns=tuple(columns),
            content_table=content_table,
            content_rowid=content_rowid,
            tokenize=tokenize,
        )
        await self._create_fts(fts_def)

    async def _create_fts(self, fts_def: FtsTable) -> None:
        """Create FTS5 virtual table and sync triggers.

        Args:
            fts_def: FTS table definition.
        """
        cols = ", ".join(fts_def.columns)
        await self._backend.ensure_schema(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts_def.name} USING fts5(\n"
            f"    {cols},\n"
            f"    content={fts_def.content_table},\n"
            f"    content_rowid={fts_def.content_rowid},\n"
            f"    tokenize='{fts_def.tokenize}'\n"
            f")"
        )

        fts_cols = ", ".join(fts_def.columns)
        new_vals = ", ".join(f"new.{c}" for c in fts_def.columns)
        old_vals = ", ".join(f"old.{c}" for c in fts_def.columns)
        ct = fts_def.content_table
        base = fts_def.name
        rowid = fts_def.content_rowid

        # AFTER INSERT
        await self._backend.ensure_schema(
            f"CREATE TRIGGER IF NOT EXISTS {base}_ai AFTER INSERT ON {ct} BEGIN\n"
            f"    INSERT INTO {base}(rowid, {fts_cols})\n"
            f"    VALUES (new.{rowid}, {new_vals});\n"
            f"END"
        )

        # AFTER DELETE
        await self._backend.ensure_schema(
            f"CREATE TRIGGER IF NOT EXISTS {base}_ad AFTER DELETE ON {ct} BEGIN\n"
            f"    INSERT INTO {base}({base}, rowid, {fts_cols})\n"
            f"    VALUES ('delete', old.{rowid}, {old_vals});\n"
            f"END"
        )

        # AFTER UPDATE
        await self._backend.ensure_schema(
            f"CREATE TRIGGER IF NOT EXISTS {base}_au AFTER UPDATE ON {ct} BEGIN\n"
            f"    INSERT INTO {base}({base}, rowid, {fts_cols})\n"
            f"    VALUES ('delete', old.{rowid}, {old_vals});\n"
            f"    INSERT INTO {base}(rowid, {fts_cols})\n"
            f"    VALUES (new.{rowid}, {new_vals});\n"
            f"END"
        )

    async def drop_fts(self, name: str, *, content_table: str) -> None:
        """Drop an FTS5 table and its sync triggers.

        Args:
            name: FTS table name.
            content_table: Content table (triggers are named based on FTS table).
        """
        await self._backend.execute(f"DROP TRIGGER IF EXISTS {name}_ai")  # sylvan-sql-safe
        await self._backend.execute(f"DROP TRIGGER IF EXISTS {name}_ad")  # sylvan-sql-safe
        await self._backend.execute(f"DROP TRIGGER IF EXISTS {name}_au")  # sylvan-sql-safe
        await self._backend.execute(f"DROP TABLE IF EXISTS {name}")  # sylvan-sql-safe

    async def vec(
        self,
        name: str,
        *,
        id_column: str,
        id_type: str = "TEXT",
        dimensions: int | None = None,
    ) -> None:
        """Create a sqlite-vec virtual table.

        Silently skips if sqlite-vec extension is not available.

        Args:
            name: Virtual table name (e.g., ``symbols_vec``).
            id_column: Primary key column name.
            id_type: SQL type for the primary key column.
            dimensions: Embedding dimensions (reads from config if None).

        Example::

            await schema.vec("symbols_vec", id_column="symbol_id", dimensions=384)
        """
        if dimensions is None:
            try:
                from sylvan.config import get_config

                dimensions = get_config().embedding.dimensions
            except Exception:
                dimensions = 384

        with contextlib.suppress(Exception):
            await self._backend.execute(  # sylvan-sql-safe
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} "
                f"USING vec0({id_column} {id_type} PRIMARY KEY, "
                f"embedding FLOAT[{dimensions}])"
            )

    async def drop_vec(self, name: str) -> None:
        """Drop a sqlite-vec virtual table.

        Args:
            name: Virtual table name.
        """
        with contextlib.suppress(Exception):
            await self._backend.execute(f"DROP TABLE IF EXISTS {name}")  # sylvan-sql-safe

    async def trigger(
        self,
        name: str,
        *,
        table: str,
        event: str,
        body: str,
    ) -> None:
        """Create a trigger.

        Args:
            name: Trigger name.
            table: Table the trigger fires on.
            event: Trigger timing (e.g., ``AFTER INSERT``, ``BEFORE UPDATE``).
            body: SQL statements inside the trigger body.

        Example::

            await schema.trigger("update_timestamp",
                table="repos",
                event="AFTER UPDATE",
                body="UPDATE repos SET updated_at = datetime('now') WHERE id = new.id;",
            )
        """
        _validate_name(name)
        _validate_name(table)
        await self._backend.ensure_schema(
            f"CREATE TRIGGER IF NOT EXISTS {name} {event} ON {table} BEGIN\n    {body}\nEND"
        )

    async def drop_trigger(self, name: str) -> None:
        """Drop a trigger if it exists.

        Args:
            name: Trigger name.
        """
        _validate_name(name)
        await self._backend.execute(f"DROP TRIGGER IF EXISTS {name}")  # sylvan-sql-safe

    async def raw(self, sql: str) -> None:
        """Execute raw SQL for edge cases the builder doesn't cover.

        Args:
            sql: Raw DDL statement(s).
        """
        await self._backend.ensure_schema(sql)

    async def execute(self, sql: str, params: list | None = None) -> None:
        """Execute a DML statement (INSERT, UPDATE, DELETE).

        Args:
            sql: SQL statement.
            params: Bind parameters.
        """
        await self._backend.execute(sql, params)
        await self._backend.commit()
