"""Tests for sylvan.tools.analysis.get_recent_changes — MCP tool wrapper."""

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
    """Index a project for recent changes testing."""
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
        'def hello():\n'
        '    """Say hello."""\n'
        '    return "hello"\n',
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder
    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()
    assert result.symbols_extracted >= 1

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


class TestGetRecentChangesRepoNotFound:
    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.analysis.get_recent_changes import get_recent_changes

        with pytest.raises(RepoNotFoundError) as exc_info:
            await get_recent_changes(repo="nonexistent-repo")

        resp = exc_info.value.to_dict()
        assert "_meta" in resp
        assert resp["error"] == "repo_not_found"


class TestGetRecentChangesNoGitRepo:
    async def test_source_unavailable_returns_error(self, indexed_repo):
        """When source_path doesn't exist on disk, returns source_unavailable."""
        from sylvan.database.orm import Repo
        from sylvan.tools.analysis.get_recent_changes import get_recent_changes

        # Set source_path to a non-existent path so git can't run
        repo_obj = await Repo.where(name="test-repo").first()
        assert repo_obj is not None
        repo_obj.source_path = "/nonexistent/path/that/does/not/exist"
        await repo_obj.save()

        resp = await get_recent_changes(repo="test-repo")

        assert "_meta" in resp
        assert resp["error"] == "source_unavailable"

    async def test_no_git_history_returns_empty(self, indexed_repo):
        """When source_path exists but is not a git repo, git commands fail gracefully."""
        from sylvan.tools.analysis.get_recent_changes import get_recent_changes

        # The tmp_path project dir exists but isn't a git repo,
        # so get_changed_files will raise or return empty
        resp = await get_recent_changes(repo="test-repo")

        assert "_meta" in resp
        # Should either return empty results or an error — not crash
        if "error" not in resp:
            assert "files_changed" in resp
            assert isinstance(resp["files_changed"], list)
            assert "summary" in resp


class TestGetRecentChangesResponseStructure:
    async def test_meta_fields(self, indexed_repo):
        from sylvan.tools.analysis.get_recent_changes import get_recent_changes

        # Even if git fails, the response should have proper meta
        resp = await get_recent_changes(repo="test-repo")

        assert "_meta" in resp
        # Response should have either error structure or valid data structure
        if "error" not in resp:
            meta = resp["_meta"]
            assert "commits_back" in meta
            assert "files_changed" in meta
