"""Tests for sylvan.tools.meta.remove_repo — MCP tool wrapper."""

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
    """Index a project for removal testing."""
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
        "def hello():\n"
        '    """Say hello."""\n'
        '    return "hello"\n'
        "\n"
        "class Greeter:\n"
        '    """A greeter class."""\n'
        "    def greet(self):\n"
        "        return hello()\n",
        encoding="utf-8",
    )
    (proj / "util.py").write_text(
        'def helper():\n    """A helper function."""\n    pass\n',
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


class TestRemoveRepoBasic:
    async def test_removes_repo_and_returns_status(self, indexed_repo):
        from sylvan.tools.meta.remove_repo import remove_repo

        resp = await remove_repo(repo="test-repo")

        assert "_meta" in resp
        assert resp["status"] == "removed"
        assert resp["repo"] == "test-repo"

        meta = resp["_meta"]
        assert meta["repo"] == "test-repo"
        assert "repo_id" in meta

    async def test_cascade_deletes_all_records(self, indexed_repo):
        from sylvan.database.orm import FileRecord, Repo, Symbol
        from sylvan.tools.meta.remove_repo import remove_repo

        # Verify data exists before removal
        repo_obj = await Repo.where(name="test-repo").first()
        assert repo_obj is not None
        repo_id = repo_obj.id

        file_count_before = await FileRecord.where(repo_id=repo_id).count()
        assert file_count_before >= 2

        symbol_count_before = (
            await Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo_id).count()
        )
        assert symbol_count_before >= 3

        # Remove the repo
        await remove_repo(repo="test-repo")

        # Verify everything is gone
        repo_after = await Repo.where(name="test-repo").first()
        assert repo_after is None

        file_count_after = await FileRecord.where(repo_id=repo_id).count()
        assert file_count_after == 0


class TestRemoveRepoErrors:
    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.meta.remove_repo import remove_repo

        with pytest.raises(RepoNotFoundError) as exc_info:
            await remove_repo(repo="nonexistent-repo")

        resp = exc_info.value.to_dict()
        assert "_meta" in resp
        assert resp["error"] == "repo_not_found"

    async def test_double_remove_fails(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.meta.remove_repo import remove_repo

        # First remove succeeds
        resp = await remove_repo(repo="test-repo")
        assert resp["status"] == "removed"

        # Second remove should fail
        with pytest.raises(RepoNotFoundError):
            await remove_repo(repo="test-repo")
