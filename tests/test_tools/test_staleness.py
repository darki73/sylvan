"""Tests for sylvan.tools.support.response — staleness detection."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


@pytest.fixture
async def indexed_project(tmp_path):
    """Create backend + context and index a sample project."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text('[embedding]\nprovider = "none"\n', encoding="utf-8")
    reset_config()

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
    (proj / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()

    yield proj, result

    from sylvan.tools.support.response import _staleness_cache

    _staleness_cache.clear()
    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)
    reset_config()


class TestStalenessDetection:
    async def test_detects_changed_head(self, indexed_project):
        _proj, result = indexed_project
        from sylvan.context import get_context
        from sylvan.tools.support.response import _staleness_cache, check_staleness

        _staleness_cache.clear()

        backend = get_context().backend
        await backend.execute(
            "UPDATE repos SET git_head = 'aaa111' WHERE id = ?",
            [result.repo_id],
        )
        await backend.commit()

        with patch("sylvan.git.run_git", return_value="bbb222"):
            res = {}
            await check_staleness(result.repo_id, res)
            assert "_stale" in res

    async def test_clean_when_matching(self, indexed_project):
        _proj, result = indexed_project
        from sylvan.context import get_context
        from sylvan.tools.support.response import _staleness_cache, check_staleness

        _staleness_cache.clear()

        backend = get_context().backend
        await backend.execute(
            "UPDATE repos SET git_head = 'aaa111' WHERE id = ?",
            [result.repo_id],
        )
        await backend.commit()

        with patch("sylvan.git.run_git", return_value="aaa111"):
            res = {}
            await check_staleness(result.repo_id, res)
            assert "_stale" not in res

    async def test_skips_non_git_repo(self, indexed_project):
        _proj, result = indexed_project
        from sylvan.context import get_context
        from sylvan.tools.support.response import _staleness_cache, check_staleness

        _staleness_cache.clear()

        backend = get_context().backend
        await backend.execute(
            "UPDATE repos SET git_head = NULL WHERE id = ?",
            [result.repo_id],
        )
        await backend.commit()

        res = {}
        await check_staleness(result.repo_id, res)
        assert "_stale" not in res

    async def test_cache_cleared_by_index_folder(self, indexed_project):
        proj, result = indexed_project
        from sylvan.tools.support.response import _staleness_cache

        _staleness_cache[result.repo_id] = True

        from sylvan.tools.indexing.index_folder import index_folder

        await index_folder(str(proj), name="test-repo")

        assert result.repo_id not in _staleness_cache

    async def test_cache_prevents_repeated_checks(self, indexed_project):
        _proj, result = indexed_project
        from sylvan.context import get_context
        from sylvan.tools.support.response import _staleness_cache, check_staleness

        _staleness_cache.clear()

        backend = get_context().backend
        await backend.execute(
            "UPDATE repos SET git_head = 'aaa111' WHERE id = ?",
            [result.repo_id],
        )
        await backend.commit()

        call_count = 0

        def mock_run_git(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return "aaa111"

        with patch("sylvan.git.run_git", side_effect=mock_run_git):
            res1 = {}
            await check_staleness(result.repo_id, res1)
            assert call_count == 1

            res2 = {}
            await check_staleness(result.repo_id, res2)
            assert call_count == 1  # Still 1 -- cached, no second call
