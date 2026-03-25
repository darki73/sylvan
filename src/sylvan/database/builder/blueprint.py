"""Table blueprint — fluent column/index/constraint definitions.

The blueprint collects column and index definitions via a fluent API,
then compiles them to SQL statements.  Used as the callback argument
in ``Schema.create()`` and ``Schema.table()``.

Example::

    def define(t: Blueprint) -> None:
        t.id()
        t.text("name")
        t.foreign_id("repo_id")
        t.text("content_hash")
        t.integer("byte_size")
        t.index(["repo_id", "path"])
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Self

_SAFE_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
"""Regex pattern for validating DDL identifiers against injection."""


def _validate_name(name: str) -> str:
    """Validate a DDL identifier to prevent SQL injection.

    Args:
        name: The identifier string to validate.

    Returns:
        The validated identifier string.

    Raises:
        ValueError: If the identifier contains invalid characters.
    """
    if not _SAFE_NAME.match(name):
        raise ValueError(f"Unsafe identifier: {name!r}")
    return name


class ColumnType(StrEnum):
    """Supported column types mapped to SQL type affinity."""

    INTEGER = auto()
    TEXT = auto()
    REAL = auto()
    BLOB = auto()
    BOOLEAN = auto()


_SQL_TYPES: dict[ColumnType, str] = {
    ColumnType.INTEGER: "INTEGER",
    ColumnType.TEXT: "TEXT",
    ColumnType.REAL: "REAL",
    ColumnType.BLOB: "BLOB",
    ColumnType.BOOLEAN: "BOOLEAN",
}


@dataclass(slots=True)
class Column:
    """A single column definition built via method chaining.

    Attributes:
        name: Column name.
        col_type: SQL type affinity.
    """

    name: str
    col_type: ColumnType
    _nullable: bool = False
    _default: str | None = None
    _primary_key: bool = False
    _unique: bool = False
    _references: str | None = None
    _on_delete: str | None = None

    def __post_init__(self) -> None:
        """Validate column name on construction."""
        _validate_name(self.name)

    def nullable(self) -> Self:
        """Allow NULL values."""
        self._nullable = True
        return self

    def default(self, value: str | int | float | bool) -> Self:
        """Set a default value.

        Args:
            value: Default value. Strings are quoted, booleans become 0/1,
                expressions wrapped in parens are used verbatim.
        """
        if isinstance(value, bool):
            self._default = "1" if value else "0"
        elif isinstance(value, str):
            if value.startswith("("):
                self._default = value
            else:
                self._default = f"'{value}'"
        else:
            self._default = str(value)
        return self

    def primary_key(self) -> Self:
        """Mark as PRIMARY KEY."""
        self._primary_key = True
        return self

    def unique(self) -> Self:
        """Add a UNIQUE constraint."""
        self._unique = True
        return self

    def references(self, table: str, column: str = "id", *, on_delete: str = "CASCADE") -> Self:
        """Add a foreign key reference.

        Args:
            table: Referenced table name.
            column: Referenced column name.
            on_delete: ON DELETE action (CASCADE, SET NULL, RESTRICT, etc.).
        """
        self._references = f"{table}({column})"
        self._on_delete = on_delete
        return self

    def to_sql(self) -> str:
        """Compile to a SQL column definition fragment.

        Returns:
            SQL string like ``name TEXT NOT NULL DEFAULT 'foo' REFERENCES bars(id)``.
        """
        parts = [self.name, _SQL_TYPES[self.col_type]]

        if self._primary_key:
            parts.append("PRIMARY KEY")
        if not self._nullable and not self._primary_key:
            parts.append("NOT NULL")
        if self._unique:
            parts.append("UNIQUE")
        if self._default is not None:
            parts.append(f"DEFAULT {self._default}")
        if self._references:
            parts.append(f"REFERENCES {self._references}")
            if self._on_delete:
                parts.append(f"ON DELETE {self._on_delete}")

        return " ".join(parts)


@dataclass(slots=True, frozen=True)
class IndexDef:
    """An index to create on the table.

    Attributes:
        columns: Columns to index.
        name: Explicit name, or None to auto-generate.
        unique: Whether this is a UNIQUE index.
    """

    columns: tuple[str, ...]
    name: str | None = None
    unique: bool = False


@dataclass(slots=True, frozen=True)
class CompositePK:
    """A composite primary key constraint.

    Attributes:
        columns: Columns forming the primary key.
    """

    columns: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class FtsTable:
    """An FTS5 virtual table definition with auto-sync triggers.

    Attributes:
        name: FTS table name (e.g., ``symbols_fts``).
        columns: Columns to index in FTS.
        content_table: Source table to sync from.
        content_rowid: Rowid column in the content table.
        tokenize: FTS5 tokenizer config string.
    """

    name: str
    columns: tuple[str, ...]
    content_table: str
    content_rowid: str = "id"
    tokenize: str = "porter unicode61"


@dataclass(slots=True, frozen=True)
class VecTable:
    """A sqlite-vec virtual table definition.

    Attributes:
        name: Virtual table name (e.g., ``symbols_vec``).
        id_column: Primary key column name.
        id_type: SQL type for the primary key.
        dimensions: Embedding vector dimensions.
    """

    name: str
    id_column: str
    id_type: str = "TEXT"
    dimensions: int = 384


class Blueprint:
    """Collects column, index, and constraint definitions for a table.

    Passed as the callback argument to ``Schema.create()`` and ``Schema.table()``.
    Methods return ``self`` or ``Column`` for chaining.
    """

    def __init__(self, table_name: str) -> None:
        # Allow quoted names (e.g. '"references"') for reserved words
        bare = table_name.strip('"')
        _validate_name(bare)
        self._table_name = table_name
        self._columns: list[Column] = []
        self._indexes: list[IndexDef] = []
        self._composite_pk: CompositePK | None = None

    def id(self, name: str = "id") -> Column:
        """Auto-incrementing integer primary key.

        Args:
            name: Column name.
        """
        col = Column(name=name, col_type=ColumnType.INTEGER, _primary_key=True)
        self._columns.append(col)
        return col

    def integer(self, name: str) -> Column:
        """INTEGER column.

        Args:
            name: Column name.
        """
        col = Column(name=name, col_type=ColumnType.INTEGER)
        self._columns.append(col)
        return col

    def text(self, name: str) -> Column:
        """TEXT column.

        Args:
            name: Column name.
        """
        col = Column(name=name, col_type=ColumnType.TEXT)
        self._columns.append(col)
        return col

    def string(self, name: str) -> Column:
        """TEXT column (Laravel-style alias for text).

        Args:
            name: Column name.
        """
        return self.text(name)

    def real(self, name: str) -> Column:
        """REAL (float) column.

        Args:
            name: Column name.
        """
        col = Column(name=name, col_type=ColumnType.REAL)
        self._columns.append(col)
        return col

    def blob(self, name: str) -> Column:
        """BLOB column.

        Args:
            name: Column name.
        """
        col = Column(name=name, col_type=ColumnType.BLOB)
        self._columns.append(col)
        return col

    def boolean(self, name: str) -> Column:
        """BOOLEAN column.

        Args:
            name: Column name.
        """
        col = Column(name=name, col_type=ColumnType.BOOLEAN)
        self._columns.append(col)
        return col

    def foreign_id(self, name: str, *, table: str | None = None, on_delete: str = "CASCADE") -> Column:
        """Integer foreign key column with auto-inferred reference.

        Infers the table from the column name: ``repo_id`` -> ``repos(id)``.

        Args:
            name: Column name (e.g., ``repo_id``).
            table: Override referenced table (inferred if None).
            on_delete: ON DELETE action.
        """
        if table is None:
            base = name.removesuffix("_id")
            table = f"{base}s"
        return self.integer(name).references(table, "id", on_delete=on_delete)

    def timestamps(self) -> None:
        """Add ``created_at`` and ``updated_at`` TEXT columns."""
        self.text("created_at").default("(datetime('now'))").nullable()
        self.text("updated_at").nullable()

    def primary(self, columns: list[str]) -> None:
        """Composite primary key.

        Args:
            columns: Columns forming the primary key.
        """
        self._composite_pk = CompositePK(columns=tuple(columns))

    def index(self, columns: str | list[str], *, name: str | None = None) -> None:
        """Add an index.

        Args:
            columns: Column name or list of column names.
            name: Explicit index name (auto-generated if None).
        """
        if isinstance(columns, str):
            columns = [columns]
        self._indexes.append(IndexDef(columns=tuple(columns), name=name))

    def unique_index(self, columns: str | list[str], *, name: str | None = None) -> None:
        """Add a unique index.

        Args:
            columns: Column name or list of column names.
            name: Explicit index name (auto-generated if None).
        """
        if isinstance(columns, str):
            columns = [columns]
        self._indexes.append(IndexDef(columns=tuple(columns), name=name, unique=True))

    def unique(self, columns: list[str]) -> None:
        """Add a UNIQUE constraint via unique index.

        Args:
            columns: Columns that must be unique together.
        """
        self.unique_index(columns)

    def to_create_sql(self) -> str:
        """Compile to ``CREATE TABLE IF NOT EXISTS`` statement.

        Returns:
            Complete SQL statement.
        """
        lines = [col.to_sql() for col in self._columns]

        if self._composite_pk:
            pk_cols = ", ".join(self._composite_pk.columns)
            lines.append(f"PRIMARY KEY ({pk_cols})")

        body = ",\n    ".join(lines)
        return f"CREATE TABLE IF NOT EXISTS {self._table_name} (\n    {body}\n)"

    def to_alter_sql(self) -> list[str]:
        """Compile to ``ALTER TABLE ADD COLUMN`` statements.

        Returns:
            One SQL statement per new column.
        """
        return [f"ALTER TABLE {self._table_name} ADD COLUMN {col.to_sql()}" for col in self._columns]

    def to_index_sql(self) -> list[str]:
        """Compile all indexes to ``CREATE INDEX`` statements.

        Returns:
            One SQL statement per index.
        """
        stmts = []
        for idx in self._indexes:
            idx_name = idx.name or f"idx_{self._table_name}_{'_'.join(idx.columns)}"
            unique = "UNIQUE " if idx.unique else ""
            cols = ", ".join(idx.columns)
            stmts.append(f"CREATE {unique}INDEX IF NOT EXISTS {idx_name} ON {self._table_name}({cols})")
        return stmts
