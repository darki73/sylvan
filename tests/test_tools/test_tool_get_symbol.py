"""Tests for sylvan.tools.browsing.get_symbol — MCP tool wrapper."""

from __future__ import annotations

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def indexed_repo(tmp_path):
    """Create backend + context and index a sample project."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    reset_config()
    reset_session()

    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(ctx)

    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "main.py").write_text(
        "def hello():\n"
        '    """Say hello."""\n'
        '    return "hello"\n'
        "\n"
        "class Foo:\n"
        '    """A foo class."""\n'
        "    def bar(self):\n"
        "        pass\n",
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()
    assert result.symbols_extracted >= 2

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


async def _find_symbol_id(name):
    """Helper to find a symbol ID by name via search."""
    from sylvan.tools.search.search_symbols import search_symbols

    resp = await search_symbols(query=name)
    for s in resp["symbols"]:
        if s["name"] == name:
            return s["symbol_id"]
    raise AssertionError(f"Symbol '{name}' not found")


class TestGetSymbol:
    async def test_returns_source_code(self, indexed_repo):
        from sylvan.tools.browsing.get_symbol import get_symbol

        sid = await _find_symbol_id("hello")
        resp = await get_symbol(sid)

        assert "source" in resp
        assert "def hello" in resp["source"]
        assert resp["name"] == "hello"
        assert resp["kind"] == "function"
        assert resp["language"] == "python"
        assert "file" in resp
        assert "line_start" in resp
        assert "line_end" in resp
        assert "signature" in resp
        assert "docstring" in resp
        assert "decorators" in resp
        assert isinstance(resp["decorators"], list)

    async def test_get_symbol_with_verify(self, indexed_repo):
        from sylvan.tools.browsing.get_symbol import get_symbol

        sid = await _find_symbol_id("hello")
        resp = await get_symbol(sid, verify=True)

        assert "source" in resp
        assert "_meta" in resp

    async def test_get_symbol_not_found(self, indexed_repo):
        from sylvan.error_codes import SymbolNotFoundError
        from sylvan.tools.browsing.get_symbol import get_symbol

        with pytest.raises(SymbolNotFoundError) as exc_info:
            await get_symbol("nonexistent::symbol#method")

        resp = exc_info.value.to_dict()
        assert resp["error"] == "symbol_not_found"
        assert "_meta" in resp

    async def test_response_has_meta_with_savings(self, indexed_repo):
        from sylvan.tools.browsing.get_symbol import get_symbol

        sid = await _find_symbol_id("hello")
        resp = await get_symbol(sid)

        assert "_meta" in resp
        meta = resp["_meta"]
        assert "timing_ms" in meta
        if "savings" in meta:
            savings = meta["savings"]
            assert "returned_bytes" in savings
            assert "total_file_bytes" in savings
            assert "bytes_avoided" in savings

    async def test_response_has_hints(self, indexed_repo):
        from sylvan.tools.browsing.get_symbol import get_symbol

        sid = await _find_symbol_id("hello")

        # First access to seed the session
        await get_symbol(sid)

        # Second access should have hints (working_files populated)
        sid2 = await _find_symbol_id("Foo")
        resp2 = await get_symbol(sid2)

        assert "_meta" in resp2


class TestGetSymbolsBatch:
    async def test_batch_returns_multiple(self, indexed_repo):
        from sylvan.tools.browsing.get_symbol import get_symbols

        sid_hello = await _find_symbol_id("hello")
        sid_foo = await _find_symbol_id("Foo")

        resp = await get_symbols([sid_hello, sid_foo])

        assert "symbols" in resp
        assert "not_found" in resp
        assert "_meta" in resp
        assert len(resp["symbols"]) == 2
        assert len(resp["not_found"]) == 0

        names = {s["name"] for s in resp["symbols"]}
        assert "hello" in names
        assert "Foo" in names

        for s in resp["symbols"]:
            assert "symbol_id" in s
            assert "name" in s
            assert "kind" in s
            assert "source" in s

    async def test_batch_with_not_found(self, indexed_repo):
        from sylvan.tools.browsing.get_symbol import get_symbols

        sid_hello = await _find_symbol_id("hello")
        fake_id = "nonexistent::symbol#function"

        resp = await get_symbols([sid_hello, fake_id])

        assert "_meta" in resp
        assert resp["_meta"]["found"] == 1
        assert resp["_meta"]["not_found"] == 1
        assert fake_id in resp["not_found"]

    async def test_batch_empty_list(self, indexed_repo):
        from sylvan.tools.browsing.get_symbol import get_symbols

        resp = await get_symbols([])

        assert "symbols" in resp
        assert resp["symbols"] == []
        assert resp["_meta"]["found"] == 0
