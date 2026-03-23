# Schema and Migrations

The schema builder provides a fluent API for creating and altering tables,
indexes, FTS5 virtual tables, and sqlite-vec virtual tables. Migrations use
the builder to evolve the database schema over time.

## Schema class

The `Schema` wraps a storage backend and exposes DDL methods:

```python
from sylvan.database.builder import Schema

schema = Schema(backend)
```

### Create a table

```python
await schema.create("repos", lambda t: (
    t.id(),
    t.text("name"),
    t.text("source_path").nullable().unique(),
    t.integer("file_count").default(0),
    t.boolean("active").default(True),
    t.timestamps(),
))
```

### Alter a table

```python
await schema.table("repos", lambda t: (
    t.text("description").nullable(),
    t.real("quality_score").default(0.0),
    t.index("name"),
))
```

### Drop and rename

```python
await schema.drop("old_table")
await schema.rename("old_name", "new_name")
await schema.rename_column("repos", "path", "source_path")
await schema.drop_column("repos", "deprecated_col")
```

### FTS5 full-text search tables

```python
await schema.fts("symbols_fts",
    columns=["symbol_id", "name", "qualified_name",
             "signature", "docstring", "summary", "keywords"],
    content_table="symbols",
)
```

This creates:

- The FTS5 virtual table with the specified columns
- An `AFTER INSERT` trigger to sync new rows
- An `AFTER DELETE` trigger to remove deleted rows
- An `AFTER UPDATE` trigger to re-sync modified rows

Drop an FTS table and its triggers:

```python
await schema.drop_fts("symbols_fts", content_table="symbols")
```

### sqlite-vec virtual tables

```python
await schema.vec("symbols_vec",
    id_column="symbol_id",
    id_type="TEXT",
    dimensions=384,
)
```

If `dimensions` is omitted, it reads from `config.yaml` (default: 384). If the
sqlite-vec extension is not available, this silently does nothing.

```python
await schema.drop_vec("symbols_vec")
```

### Triggers

```python
await schema.trigger("update_timestamp",
    table="repos",
    event="AFTER UPDATE",
    body="UPDATE repos SET updated_at = datetime('now') WHERE id = new.id;",
)

await schema.drop_trigger("update_timestamp")
```

### Standalone indexes

```python
await schema.create_index("repos", ["name"], unique=True)
await schema.create_index("symbols", ["repo_id", "kind"], name="idx_symbols_repo_kind")
await schema.drop_index("idx_symbols_repo_kind")
```

### Raw SQL

```python
await schema.raw("CREATE VIEW active_repos AS SELECT * FROM repos WHERE active = 1")
await schema.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ["version", "2"])
```

## Blueprint class

The `Blueprint` is passed to `schema.create()` and `schema.table()` callbacks.
It collects column definitions and compiles them to SQL.

### Column types

```python
await schema.create("example", lambda t: (
    t.id(),                              # INTEGER PRIMARY KEY (auto-increment)
    t.text("name"),                      # TEXT NOT NULL
    t.string("label"),                   # TEXT NOT NULL (alias for text)
    t.integer("count"),                  # INTEGER NOT NULL
    t.real("score"),                     # REAL NOT NULL
    t.blob("data"),                      # BLOB NOT NULL
    t.boolean("active"),                 # BOOLEAN NOT NULL
))
```

### Column modifiers

Modifiers chain after the column type:

```python
await schema.create("files", lambda t: (
    t.id(),
    t.text("path"),
    t.text("content").nullable(),              # allows NULL
    t.integer("size").default(0),              # DEFAULT 0
    t.text("hash").unique(),                   # UNIQUE constraint
    t.text("created_at").default("(datetime('now'))"),  # SQL expression default
))
```

### Foreign keys

```python
await schema.create("symbols", lambda t: (
    t.id(),
    t.text("name"),

    # Auto-inferred: repo_id -> repos(id) ON DELETE CASCADE
    t.foreign_id("repo_id"),

    # Explicit table reference
    t.foreign_id("file_id", table="files"),

    # Manual foreign key with custom on_delete
    t.integer("parent_id").nullable().references("symbols", "id", on_delete="SET NULL"),
))
```

`foreign_id("repo_id")` infers the table as `repos` from the column name
(strips `_id`, adds `s`). Override with the `table` kwarg.

### Indexes

```python
await schema.create("symbols", lambda t: (
    t.id(),
    t.text("name"),
    t.text("kind"),
    t.foreign_id("repo_id"),

    # Single-column index
    t.index("name"),

    # Multi-column index
    t.index(["repo_id", "kind"]),

    # Unique index
    t.unique_index(["repo_id", "name"]),

    # Named index
    t.index("kind", name="idx_sym_kind"),
))
```

### Composite primary key

```python
await schema.create("workspace_repos", lambda t: (
    t.integer("workspace_id"),
    t.integer("repo_id"),
    t.primary(["workspace_id", "repo_id"]),
))
```

### Timestamps convenience

```python
await schema.create("repos", lambda t: (
    t.id(),
    t.text("name"),
    t.timestamps(),  # adds created_at and updated_at TEXT columns
))
```

`timestamps()` adds:

- `created_at TEXT DEFAULT (datetime('now'))` (nullable)
- `updated_at TEXT` (nullable)

## Creating a migration

```bash
uv run sylvan migrate create "add quality scores"
```

This generates a numbered file in `src/sylvan/database/migrations/`:

```python
"""Migration 005: add quality scores."""

from sylvan.database.backends.base import Dialect, StorageBackend
from sylvan.database.builder import Schema


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    """Apply this migration."""
    schema = Schema(backend)


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    """Reverse this migration."""
    schema = Schema(backend)
```

Fill in the `up` and `down` functions:

```python
async def up(backend: StorageBackend, dialect: Dialect) -> None:
    schema = Schema(backend)

    await schema.create("quality_records", lambda t: (
        t.id(),
        t.foreign_id("repo_id"),
        t.foreign_id("file_id"),
        t.text("symbol_id").nullable(),
        t.real("complexity").default(0.0),
        t.boolean("has_tests").default(False),
        t.boolean("has_docs").default(False),
        t.timestamps(),
        t.index("repo_id"),
        t.index("file_id"),
        t.unique_index(["file_id", "symbol_id"]),
    ))


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    schema = Schema(backend)
    await schema.drop("quality_records")
```

## Running migrations

```bash
# Preview pending migrations without running them
uv run sylvan migrate --dry-run

# Run all pending migrations
uv run sylvan migrate

# Roll back the most recent migration
uv run sylvan migrate rollback
```

## Migration file naming

Files are auto-numbered: `001_initial_schema.py`, `002_add_imports.py`,
`003_add_quality_scores.py`. The runner discovers them by scanning the
`src/sylvan/database/migrations/` directory, sorting by the numeric prefix, and
running any with a version higher than the current database version.

## Complete migration example

A migration that adds a new table, an FTS index, and a vec table:

```python
"""Migration 006: add code snippets."""

from sylvan.database.backends.base import Dialect, StorageBackend
from sylvan.database.builder import Schema


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    schema = Schema(backend)

    await schema.create("snippets", lambda t: (
        t.id(),
        t.foreign_id("repo_id"),
        t.foreign_id("file_id"),
        t.text("title"),
        t.text("content"),
        t.text("language").nullable(),
        t.integer("line_start"),
        t.integer("line_end"),
        t.timestamps(),
        t.index("repo_id"),
        t.index(["file_id", "line_start"]),
    ))

    await schema.fts("snippets_fts",
        columns=["title", "content"],
        content_table="snippets",
    )

    await schema.vec("snippets_vec",
        id_column="snippet_id",
        id_type="INTEGER",
        dimensions=384,
    )


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    schema = Schema(backend)
    await schema.drop_vec("snippets_vec")
    await schema.drop_fts("snippets_fts", content_table="snippets")
    await schema.drop("snippets")
```
