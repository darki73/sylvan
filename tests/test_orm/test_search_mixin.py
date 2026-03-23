"""Tests for sylvan.database.orm.query.search — FTS search mixin and vector search setup."""

from __future__ import annotations

import pytest

from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm import Symbol
from sylvan.database.orm.query.builder import QueryBuilder
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


@pytest.fixture
async def search_ctx(tmp_path):
    """Backend + context for search tests."""
    db_path = tmp_path / "search_test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(ctx)
    yield ctx
    reset_context(token)
    await backend.disconnect()


class TestSearchMethod:
    """Tests for QueryBuilder.search() fluent method."""

    def test_sets_fts_query(self):
        builder = QueryBuilder(Symbol)
        result = builder.search("hello world")
        assert result is builder
        assert builder._fts_query == "hello OR world"

    def test_search_with_special_chars(self):
        builder = QueryBuilder(Symbol)
        builder.search("foo(bar)")
        assert "foo" in builder._fts_query
        assert "bar" in builder._fts_query
        assert "(" not in builder._fts_query

    def test_search_empty_string(self):
        builder = QueryBuilder(Symbol)
        builder.search("")
        assert builder._fts_query == ""


class TestSimilarTo:
    """Tests for QueryBuilder.similar_to() fluent method."""

    def test_sets_vec_text(self):
        builder = QueryBuilder(Symbol)
        result = builder.similar_to("search text", k=10, weight=0.5)
        assert result is builder
        assert builder._vec_text == "search text"
        assert builder._vec_k == 10
        assert builder._vec_weight == 0.5

    def test_sets_vec_vector(self):
        vec = [0.1, 0.2, 0.3]
        builder = QueryBuilder(Symbol)
        builder.similar_to(vec, k=5)
        assert builder._vec_vector == vec
        assert builder._vec_k == 5

    def test_default_weight(self):
        builder = QueryBuilder(Symbol)
        builder.similar_to("text")
        assert builder._vec_weight == 0.3
        assert builder._vec_k == 20


class TestResolveQueryVector:
    """Tests for _resolve_query_vector()."""

    def test_returns_explicit_vector(self):
        builder = QueryBuilder(Symbol)
        builder._vec_vector = [1.0, 2.0, 3.0]
        assert builder._resolve_query_vector() == [1.0, 2.0, 3.0]

    def test_returns_none_when_nothing_set(self):
        builder = QueryBuilder(Symbol)
        assert builder._resolve_query_vector() is None


class TestFtsExecution:
    """Integration test: FTS search against real sqlite backend."""

    async def test_fts_search_returns_results(self, search_ctx):
        """Insert a symbol and verify FTS search finds it."""
        backend = search_ctx.backend
        # Insert a repo
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["test-repo", "/test/repo"],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (1, 'test.py', 'python', 'hash1', 100)",
            [],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["sym1", 1, "calculate_total", "module.calculate_total", "function", "python", 1, 10, 0, 100],
        )
        await backend.commit()

        results = await Symbol.search("calculate_total").get()
        assert len(results) >= 1
        names = [r.name for r in results]
        assert "calculate_total" in names

    async def test_fts_search_no_results(self, search_ctx):
        """FTS search with no matches returns empty list."""
        results = await Symbol.search("nonexistent_xyz_symbol").get()
        assert results == []

    async def test_fts_search_with_where(self, search_ctx):
        """FTS search combined with where clause."""
        backend = search_ctx.backend
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["test-repo", "/test/repo"],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (1, 'test.py', 'python', 'hash1', 100)",
            [],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["sym1", 1, "my_function", "mod.my_function", "function", "python", 1, 10, 0, 100],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["sym2", 1, "MyClass", "mod.MyClass", "class", "python", 11, 20, 100, 200],
        )
        await backend.commit()

        # Search with kind filter
        results = await Symbol.search("my_function").where(kind="function").get()
        assert len(results) >= 1
        assert all(r.kind == "function" for r in results)
