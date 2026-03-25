"""Tests for sylvan.tools.search.search_similar — MCP tool wrapper."""

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
    """Index a project with multiple symbols for similarity testing."""
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
    (proj / "utils.py").write_text(
        "def fetch_data(url: str) -> dict:\n"
        '    """Fetch data from a URL."""\n'
        "    pass\n"
        "\n"
        "def get_data(endpoint: str) -> dict:\n"
        '    """Get data from an endpoint."""\n'
        "    pass\n"
        "\n"
        "def process_items(items: list) -> list:\n"
        '    """Process a list of items."""\n'
        "    pass\n",
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()
    assert result.symbols_extracted >= 3

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


async def _find_symbol_id(name: str) -> str:
    """Find a symbol ID by name."""
    from sylvan.tools.search.search_symbols import search_symbols

    resp = await search_symbols(query=name)
    for s in resp["symbols"]:
        if s["name"] == name:
            return s["symbol_id"]
    raise AssertionError(f"Symbol '{name}' not found")


class TestSearchSimilarBasic:
    async def test_returns_correct_structure(self, indexed_repo):
        from sylvan.tools.search.search_similar import search_similar_symbols

        sid = await _find_symbol_id("fetch_data")
        resp = await search_similar_symbols(symbol_id=sid)

        assert "_meta" in resp
        assert "source" in resp
        assert "similar" in resp
        assert isinstance(resp["similar"], list)

        meta = resp["_meta"]
        assert "results_count" in meta
        assert meta["source_symbol"] == sid

    async def test_source_summary_in_response(self, indexed_repo):
        from sylvan.tools.search.search_similar import search_similar_symbols

        sid = await _find_symbol_id("fetch_data")
        resp = await search_similar_symbols(symbol_id=sid)

        source = resp["source"]
        assert "name" in source
        assert source["name"] == "fetch_data"
        assert "symbol_id" in source

    async def test_similar_results_exclude_source(self, indexed_repo):
        from sylvan.tools.search.search_similar import search_similar_symbols

        sid = await _find_symbol_id("fetch_data")
        resp = await search_similar_symbols(symbol_id=sid)

        # The source symbol should not appear in the similar list
        similar_ids = [s["symbol_id"] for s in resp["similar"]]
        assert sid not in similar_ids


class TestSearchSimilarErrors:
    async def test_symbol_not_found(self, indexed_repo):
        from sylvan.error_codes import SymbolNotFoundError
        from sylvan.tools.search.search_similar import search_similar_symbols

        with pytest.raises(SymbolNotFoundError) as exc_info:
            await search_similar_symbols(symbol_id="nonexistent::sym#function")

        resp = exc_info.value.to_dict()
        assert "_meta" in resp
        assert resp["error"] == "symbol_not_found"

    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.search.search_similar import search_similar_symbols

        sid = await _find_symbol_id("fetch_data")
        with pytest.raises(RepoNotFoundError) as exc_info:
            await search_similar_symbols(symbol_id=sid, repo="nonexistent-repo")

        resp = exc_info.value.to_dict()
        assert "_meta" in resp
        assert resp["error"] == "repo_not_found"


class TestSearchSimilarWithRepoFilter:
    async def test_filter_by_existing_repo(self, indexed_repo):
        from sylvan.tools.search.search_similar import search_similar_symbols

        sid = await _find_symbol_id("fetch_data")
        resp = await search_similar_symbols(symbol_id=sid, repo="test-repo")

        assert "_meta" in resp
        assert "similar" in resp
        # Results should all be from the filtered repo (may be empty without embeddings)
        assert isinstance(resp["similar"], list)
