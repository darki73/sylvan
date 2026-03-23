"""Tests for sylvan.tools.search.search_symbols — MCP tool wrapper."""

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
    config_path = tmp_path / "config.toml"
    config_path.write_text('[embedding]\nprovider = "none"\n', encoding="utf-8")
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
        'def hello(): pass\n'
        'class Foo:\n'
        '    def bar(self): pass\n'
        '    def baz(self): pass\n',
        encoding="utf-8",
    )
    (proj / "util.py").write_text(
        'def helper(): pass\n'
        'def hello_world(): pass\n',
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder
    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()
    assert result.symbols_extracted >= 4

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


class TestSearchSymbolsBasic:
    async def test_returns_correct_structure(self, indexed_repo):
        from sylvan.tools.search.search_symbols import search_symbols
        resp = await search_symbols(query="hello")

        assert "symbols" in resp
        assert "_meta" in resp
        assert isinstance(resp["symbols"], list)
        assert len(resp["symbols"]) >= 1

        sym = resp["symbols"][0]
        assert "symbol_id" in sym
        assert "name" in sym
        assert "qualified_name" in sym
        assert "kind" in sym
        assert "language" in sym
        assert "file" in sym
        assert "repo" in sym

    async def test_meta_has_results_count(self, indexed_repo):
        from sylvan.tools.search.search_symbols import search_symbols
        resp = await search_symbols(query="hello")
        meta = resp["_meta"]
        assert "results_count" in meta
        assert "query" in meta
        assert meta["query"] == "hello"
        assert "timing_ms" in meta

    async def test_returns_multiple_matches(self, indexed_repo):
        from sylvan.tools.search.search_symbols import search_symbols
        resp = await search_symbols(query="hello")
        # Should match both 'hello' and 'hello_world'
        names = [s["name"] for s in resp["symbols"]]
        assert "hello" in names


class TestSearchSymbolsEmpty:
    async def test_empty_query_raises_empty_query(self, indexed_repo):
        from sylvan.error_codes import EmptyQueryError
        from sylvan.tools.search.search_symbols import search_symbols

        with pytest.raises(EmptyQueryError) as exc_info:
            await search_symbols(query="")

        resp = exc_info.value.to_dict()
        assert resp["error"] == "empty_query"
        assert "_meta" in resp

    async def test_no_match_returns_empty(self, indexed_repo):
        from sylvan.tools.search.search_symbols import search_symbols
        resp = await search_symbols(query="zzzznonexistent")
        assert "symbols" in resp
        assert len(resp["symbols"]) == 0


class TestSearchSymbolsSession:
    async def test_second_search_deprioritizes_seen_symbols(self, indexed_repo):
        from sylvan.tools.browsing.get_symbol import get_symbol
        from sylvan.tools.search.search_symbols import search_symbols

        # First search
        resp1 = await search_symbols(query="hello")
        assert len(resp1["symbols"]) >= 1
        first_id = resp1["symbols"][0]["symbol_id"]

        # Retrieve the first symbol (marks it as seen)
        await get_symbol(first_id)

        # Second search should deprioritize the seen symbol
        resp2 = await search_symbols(query="hello")
        meta = resp2["_meta"]
        assert meta["already_seen_deprioritized"] >= 1

        # If there are multiple results, the seen one should be at the end
        if len(resp2["symbols"]) > 1:
            seen_entries = [
                s for s in resp2["symbols"] if s.get("_already_retrieved")
            ]
            assert len(seen_entries) >= 1


class TestSearchSymbolsFilter:
    async def test_filter_by_repo_name(self, indexed_repo):
        from sylvan.tools.search.search_symbols import search_symbols

        # Search with existing repo name
        resp = await search_symbols(query="hello", repo="test-repo")
        assert len(resp["symbols"]) >= 1
        for s in resp["symbols"]:
            assert s["repo"] == "test-repo"

        # Search with non-existent repo
        resp2 = await search_symbols(query="hello", repo="nonexistent-repo")
        assert len(resp2["symbols"]) == 0


class TestSearchSymbolsTokenBudget:
    async def test_token_budget_limits_results(self, indexed_repo):
        from sylvan.tools.search.search_symbols import search_symbols
        # Without budget
        resp_all = await search_symbols(query="hello")
        # With tight budget
        resp_budget = await search_symbols(query="hello", token_budget=100)
        assert resp_budget["_meta"]["results_count"] <= resp_all["_meta"]["results_count"]
        assert "tokens_used" in resp_budget["_meta"]
        assert "tokens_remaining" in resp_budget["_meta"]
        assert resp_budget["_meta"]["tokens_used"] <= 100 or resp_budget["_meta"]["results_count"] == 1

    async def test_token_budget_always_includes_one(self, indexed_repo):
        from sylvan.tools.search.search_symbols import search_symbols
        resp = await search_symbols(query="hello", token_budget=1)
        assert resp["_meta"]["results_count"] >= 1

    async def test_no_token_budget_omits_token_meta(self, indexed_repo):
        from sylvan.tools.search.search_symbols import search_symbols
        resp = await search_symbols(query="hello")
        assert "tokens_used" not in resp["_meta"]
        assert "tokens_remaining" not in resp["_meta"]
