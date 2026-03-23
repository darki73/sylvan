"""Tests for the fluent schema builder."""

import pytest

from sylvan.database.builder import Blueprint, Column, ColumnType, Schema


class TestColumn:
    def test_basic_text(self):
        col = Column(name="title", col_type=ColumnType.TEXT)
        assert col.to_sql() == "title TEXT NOT NULL"

    def test_nullable(self):
        col = Column(name="bio", col_type=ColumnType.TEXT)
        col.nullable()
        assert col.to_sql() == "bio TEXT"

    def test_default_string(self):
        col = Column(name="role", col_type=ColumnType.TEXT)
        col.default("user")
        assert col.to_sql() == "role TEXT NOT NULL DEFAULT 'user'"

    def test_default_integer(self):
        col = Column(name="count", col_type=ColumnType.INTEGER)
        col.default(0)
        assert col.to_sql() == "count INTEGER NOT NULL DEFAULT 0"

    def test_default_boolean(self):
        col = Column(name="active", col_type=ColumnType.BOOLEAN)
        col.default(True)
        assert col.to_sql() == "active BOOLEAN NOT NULL DEFAULT 1"

    def test_default_expression(self):
        col = Column(name="ts", col_type=ColumnType.TEXT)
        col.default("(datetime('now'))")
        assert col.to_sql() == "ts TEXT NOT NULL DEFAULT (datetime('now'))"

    def test_primary_key(self):
        col = Column(name="id", col_type=ColumnType.INTEGER)
        col.primary_key()
        assert col.to_sql() == "id INTEGER PRIMARY KEY"

    def test_unique(self):
        col = Column(name="email", col_type=ColumnType.TEXT)
        col.unique()
        assert col.to_sql() == "email TEXT NOT NULL UNIQUE"

    def test_references(self):
        col = Column(name="repo_id", col_type=ColumnType.INTEGER)
        col.references("repos", "id", on_delete="CASCADE")
        assert col.to_sql() == "repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE"

    def test_chaining(self):
        col = Column(name="path", col_type=ColumnType.TEXT)
        result = col.nullable().default("").unique()
        assert result is col
        assert "TEXT" in col.to_sql()
        assert "UNIQUE" in col.to_sql()


class TestBlueprint:
    def test_create_simple_table(self):
        bp = Blueprint("users")
        bp.id()
        bp.text("name")
        bp.text("email").unique()

        sql = bp.to_create_sql()
        assert "CREATE TABLE IF NOT EXISTS users" in sql
        assert "id INTEGER PRIMARY KEY" in sql
        assert "name TEXT NOT NULL" in sql
        assert "email TEXT NOT NULL UNIQUE" in sql

    def test_foreign_id_infers_table(self):
        bp = Blueprint("files")
        bp.foreign_id("repo_id")

        sql = bp.to_create_sql()
        assert "repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE" in sql

    def test_foreign_id_explicit_table(self):
        bp = Blueprint("symbols")
        bp.foreign_id("file_id", table="files")

        sql = bp.to_create_sql()
        assert "REFERENCES files(id)" in sql

    def test_composite_primary_key(self):
        bp = Blueprint("usage_stats")
        bp.integer("repo_id")
        bp.text("date")
        bp.primary(["repo_id", "date"])

        sql = bp.to_create_sql()
        assert "PRIMARY KEY (repo_id, date)" in sql

    def test_index_generation(self):
        bp = Blueprint("symbols")
        bp.id()
        bp.text("name")
        bp.index("name")
        bp.index(["kind", "language"])

        stmts = bp.to_index_sql()
        assert len(stmts) == 2
        assert "idx_symbols_name" in stmts[0]
        assert "idx_symbols_kind_language" in stmts[1]

    def test_unique_index(self):
        bp = Blueprint("repos")
        bp.unique_index("source_path")

        stmts = bp.to_index_sql()
        assert "UNIQUE INDEX" in stmts[0]

    def test_alter_table(self):
        bp = Blueprint("repos")
        bp.text("description").nullable()
        bp.boolean("active").default(True)

        stmts = bp.to_alter_sql()
        assert len(stmts) == 2
        assert "ALTER TABLE repos ADD COLUMN description TEXT" in stmts[0]
        assert "ALTER TABLE repos ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1" in stmts[1]

    def test_timestamps(self):
        bp = Blueprint("events")
        bp.id()
        bp.timestamps()

        sql = bp.to_create_sql()
        assert "created_at TEXT" in sql
        assert "updated_at TEXT" in sql
        assert "datetime('now')" in sql

    def test_all_column_types(self):
        bp = Blueprint("test")
        bp.integer("a")
        bp.text("b")
        bp.string("c")
        bp.real("d")
        bp.blob("e")
        bp.boolean("f")

        sql = bp.to_create_sql()
        assert "a INTEGER" in sql
        assert "b TEXT" in sql
        assert "c TEXT" in sql
        assert "d REAL" in sql
        assert "e BLOB" in sql
        assert "f BOOLEAN" in sql

    def test_index_single_column_as_string(self):
        bp = Blueprint("t")
        bp.index("name")
        assert len(bp._indexes) == 1
        assert bp._indexes[0].columns == ("name",)

    def test_explicit_index_name(self):
        bp = Blueprint("t")
        bp.index(["a", "b"], name="my_custom_idx")
        stmts = bp.to_index_sql()
        assert "my_custom_idx" in stmts[0]


class TestSchema:
    @pytest.fixture
    def mock_backend(self):
        """A minimal mock backend that records executed SQL."""
        class MockBackend:
            def __init__(self):
                self.executed = []
                self.schemas = []

            async def execute(self, sql, params=None):
                self.executed.append(sql)
                return 0

            async def ensure_schema(self, ddl):
                self.schemas.append(ddl)

            async def commit(self):
                pass

        return MockBackend()

    @pytest.mark.asyncio
    async def test_create_table(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.create("repos", lambda t: (
            t.id(),
            t.text("name"),
        ))

        assert len(mock_backend.schemas) >= 1
        assert "CREATE TABLE IF NOT EXISTS repos" in mock_backend.schemas[0]

    @pytest.mark.asyncio
    async def test_create_with_indexes(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.create("files", lambda t: (
            t.id(),
            t.text("path"),
            t.index("path"),
        ))

        # First schema call is CREATE TABLE, second is CREATE INDEX
        assert len(mock_backend.schemas) == 2
        assert "CREATE TABLE" in mock_backend.schemas[0]
        assert "CREATE INDEX" in mock_backend.schemas[1]

    @pytest.mark.asyncio
    async def test_drop(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.drop("repos")
        assert "DROP TABLE IF EXISTS repos" in mock_backend.executed

    @pytest.mark.asyncio
    async def test_drop_quoted(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.drop_quoted("references")
        assert 'DROP TABLE IF EXISTS "references"' in mock_backend.executed

    @pytest.mark.asyncio
    async def test_rename(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.rename("old_table", "new_table")
        assert "ALTER TABLE old_table RENAME TO new_table" in mock_backend.executed

    @pytest.mark.asyncio
    async def test_fts_creates_table_and_triggers(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.fts("test_fts",
            columns=["name", "body"],
            content_table="docs",
        )

        # Should create: virtual table + 3 triggers
        assert len(mock_backend.schemas) == 4
        assert "USING fts5" in mock_backend.schemas[0]
        assert "AFTER INSERT" in mock_backend.schemas[1]
        assert "AFTER DELETE" in mock_backend.schemas[2]
        assert "AFTER UPDATE" in mock_backend.schemas[3]

    @pytest.mark.asyncio
    async def test_drop_fts_cleans_triggers(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.drop_fts("test_fts", content_table="docs")

        assert "DROP TRIGGER IF EXISTS test_fts_ai" in mock_backend.executed
        assert "DROP TRIGGER IF EXISTS test_fts_ad" in mock_backend.executed
        assert "DROP TRIGGER IF EXISTS test_fts_au" in mock_backend.executed
        assert "DROP TABLE IF EXISTS test_fts" in mock_backend.executed

    @pytest.mark.asyncio
    async def test_vec_creates_table(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.vec("sym_vec", id_column="symbol_id", dimensions=384)

        assert any("vec0" in s for s in mock_backend.executed)
        assert any("FLOAT[384]" in s for s in mock_backend.executed)

    @pytest.mark.asyncio
    async def test_table_alter(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.table("repos", lambda t: (
            t.text("stars").nullable(),
            t.index("stars"),
        ))

        assert any("ALTER TABLE" in s for s in mock_backend.executed)
        assert any("CREATE INDEX" in s for s in mock_backend.schemas)

    @pytest.mark.asyncio
    async def test_create_index_standalone(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.create_index("repos", ["name", "version"], unique=True)

        assert any("UNIQUE INDEX" in s for s in mock_backend.schemas)

    @pytest.mark.asyncio
    async def test_trigger(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.trigger("my_trigger",
            table="repos",
            event="AFTER UPDATE",
            body="UPDATE repos SET updated_at = datetime('now') WHERE id = new.id;",
        )

        assert any("CREATE TRIGGER" in s for s in mock_backend.schemas)
        assert any("AFTER UPDATE" in s for s in mock_backend.schemas)

    @pytest.mark.asyncio
    async def test_raw(self, mock_backend):
        schema = Schema(mock_backend)
        await schema.raw("PRAGMA journal_mode=WAL")
        assert "PRAGMA journal_mode=WAL" in mock_backend.schemas

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_backend):
        async with Schema(mock_backend) as schema:
            await schema.create("t", lambda t: t.id())
        assert len(mock_backend.schemas) >= 1
