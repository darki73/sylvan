"""Tests for sylvan.tools.indexing.index_file — surgical single-file reindex."""

from __future__ import annotations

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


@pytest.fixture
async def indexed_project(tmp_path):
    """Create backend + context and index a sample project, returning the project path."""
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
    (proj / "util.py").write_text("def helper(): pass\n", encoding="utf-8")

    from sylvan.indexing.pipeline.orchestrator import index_folder

    await index_folder(str(proj), name="test-repo")
    await backend.commit()

    yield proj

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)
    reset_config()


class TestIndexFile:
    async def test_reindexes_changed_file(self, indexed_project):
        proj = indexed_project
        (proj / "main.py").write_text("def hello(): pass\ndef goodbye(): pass\n", encoding="utf-8")

        from sylvan.tools.indexing.index_file import index_file

        resp = await index_file(repo="test-repo", file_path="main.py")

        assert resp["status"] == "updated"
        assert resp["symbols_extracted"] >= 2

    async def test_unchanged_file_returns_unchanged(self, indexed_project):
        from sylvan.tools.indexing.index_file import index_file

        resp = await index_file(repo="test-repo", file_path="main.py")

        assert resp["status"] == "unchanged"
        assert resp["symbols_extracted"] == 0

    async def test_repo_not_found(self, indexed_project):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.indexing.index_file import index_file

        with pytest.raises(RepoNotFoundError):
            await index_file(repo="nonexistent", file_path="main.py")

    async def test_file_not_found(self, indexed_project):
        from sylvan.error_codes import IndexFileNotFoundError as SylvanFileNotFound
        from sylvan.tools.indexing.index_file import index_file

        with pytest.raises(SylvanFileNotFound):
            await index_file(repo="test-repo", file_path="nonexistent.py")

    async def test_path_traversal_rejected(self, indexed_project):
        from sylvan.error_codes import IndexFileNotFoundError as SylvanFileNotFound
        from sylvan.tools.indexing.index_file import index_file

        with pytest.raises(SylvanFileNotFound):
            await index_file(repo="test-repo", file_path="../../etc/passwd")

    async def test_new_file_indexed(self, indexed_project):
        proj = indexed_project
        (proj / "new_module.py").write_text("class Widget:\n    def render(self): pass\n", encoding="utf-8")

        from sylvan.tools.indexing.index_file import index_file

        resp = await index_file(repo="test-repo", file_path="new_module.py")

        assert resp["status"] == "updated"
        assert resp["symbols_extracted"] >= 2
