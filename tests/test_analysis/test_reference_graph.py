"""Tests for sylvan.analysis.structure.reference_graph — reference graph and helpers."""

from __future__ import annotations

import pytest

from sylvan.analysis.structure.reference_graph import (
    _name_appears_in,
    get_references_from,
    get_references_to,
)
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


class TestNameAppearsIn:
    def test_simple_match(self):
        assert _name_appears_in("calculate", "result = calculate(x)") is True

    def test_no_match(self):
        assert _name_appears_in("missing", "result = calculate(x)") is False

    def test_word_boundary(self):
        assert _name_appears_in("calc", "recalculate(x)") is False

    def test_short_name_rejected(self):
        assert _name_appears_in("x", "x = 1") is False

    def test_single_char_rejected(self):
        assert _name_appears_in("a", "a = 1") is False

    def test_two_char_name(self):
        assert _name_appears_in("fn", "result = fn(x)") is True

    def test_underscore_name(self):
        assert _name_appears_in("my_func", "call my_func() here") is True

    def test_name_at_start(self):
        assert _name_appears_in("start", "start the process") is True

    def test_name_at_end(self):
        assert _name_appears_in("end", "this is the end") is True

    def test_empty_text(self):
        assert _name_appears_in("name", "") is False

    def test_empty_name(self):
        assert _name_appears_in("", "some text") is False


@pytest.fixture
async def ref_ctx(tmp_path):
    """Backend + context for reference graph tests."""
    db_path = tmp_path / "ref_test.db"
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


class TestGetReferencesTo:
    async def test_returns_empty_for_unknown_symbol(self, ref_ctx):
        result = await get_references_to("nonexistent::symbol")
        assert result == []

    async def test_returns_references(self, ref_ctx):
        backend = ref_ctx.backend
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["test-repo", "/test/repo"],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (1, 'a.py', 'python', 'h1', 100)",
            [],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (1, 'b.py', 'python', 'h2', 100)",
            [],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["src_sym", 1, "caller", "a.caller", "function", "python", 1, 5, 0, 50],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["tgt_sym", 2, "target", "b.target", "function", "python", 1, 5, 0, 50],
        )
        await backend.execute(
            'INSERT INTO "references" (source_symbol_id, target_symbol_id, target_specifier) VALUES (?, ?, ?)',
            ["src_sym", "tgt_sym", "b"],
        )
        await backend.commit()

        refs = await get_references_to("tgt_sym")
        assert len(refs) == 1
        assert refs[0]["source_symbol_id"] == "src_sym"
        assert refs[0]["name"] == "caller"


class TestGetReferencesFrom:
    async def test_returns_empty_for_unknown_symbol(self, ref_ctx):
        result = await get_references_from("nonexistent::symbol")
        assert result == []

    async def test_returns_references(self, ref_ctx):
        backend = ref_ctx.backend
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["test-repo", "/test/repo"],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (1, 'a.py', 'python', 'h1', 100)",
            [],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (1, 'b.py', 'python', 'h2', 100)",
            [],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["src_sym", 1, "caller", "a.caller", "function", "python", 1, 5, 0, 50],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["tgt_sym", 2, "target", "b.target", "function", "python", 1, 5, 0, 50],
        )
        await backend.execute(
            'INSERT INTO "references" (source_symbol_id, target_symbol_id, target_specifier) VALUES (?, ?, ?)',
            ["src_sym", "tgt_sym", "b"],
        )
        await backend.commit()

        refs = await get_references_from("src_sym")
        assert len(refs) == 1
        assert refs[0]["target_symbol_id"] == "tgt_sym"
        assert refs[0]["name"] == "target"
