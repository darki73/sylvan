"""Tests for sylvan.tools.analysis.get_symbol_diff."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def indexed_repo(tmp_path):
    """Index a project for symbol diff tests."""
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
    (proj / "math.py").write_text(
        "def add(a, b):\n"
        '    """Add two numbers."""\n'
        "    return a + b\n"
        "\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
        "\n"
        "class Calculator:\n"
        "    pass\n",
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="diff-repo")
    await backend.commit()
    assert result.symbols_extracted >= 3

    yield proj

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


class TestGetSymbolDiff:
    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.analysis.get_symbol_diff import get_symbol_diff

        with pytest.raises(RepoNotFoundError):
            await get_symbol_diff(repo="nonexistent")

    async def test_source_unavailable(self, indexed_repo, tmp_path):
        from sylvan.database.orm import Repo
        from sylvan.tools.analysis.get_symbol_diff import get_symbol_diff

        repo_obj = await Repo.where(name="diff-repo").first()
        await repo_obj.update(source_path=str(tmp_path / "gone"))

        resp = await get_symbol_diff(repo="diff-repo")
        assert "source_unavailable" in resp.get("error", "")

    async def test_no_changes_same_content(self, indexed_repo):
        """When old content matches current, no symbols are added or removed."""
        from sylvan.tools.analysis.get_symbol_diff import get_symbol_diff

        old_content = (indexed_repo / "math.py").read_text(encoding="utf-8")

        with patch("sylvan.git.run_git", return_value=old_content):
            resp = await get_symbol_diff(repo="diff-repo", commit="HEAD~1")

        assert "_meta" in resp
        assert resp["summary"]["added"] == 0
        assert resp["summary"]["removed"] == 0
        # changed + unchanged should account for all symbols
        assert resp["summary"]["changed"] + resp["summary"]["unchanged"] >= 3

    async def test_detects_added_symbols(self, indexed_repo):
        """When old file is empty, all current symbols are added."""
        from sylvan.tools.analysis.get_symbol_diff import get_symbol_diff

        with patch("sylvan.git.run_git", return_value=""):
            resp = await get_symbol_diff(repo="diff-repo", file_path="math.py")

        assert "_meta" in resp
        assert resp["summary"]["added"] >= 3
        assert resp["summary"]["removed"] == 0

    async def test_detects_removed_symbols(self, indexed_repo):
        """When old file had extra symbols, they show as removed."""
        from sylvan.tools.analysis.get_symbol_diff import get_symbol_diff

        old_content = (
            "def add(a, b):\n"
            "    return a + b\n"
            "\n"
            "def subtract(a, b):\n"
            "    return a - b\n"
            "\n"
            "class Calculator:\n"
            "    pass\n"
            "\n"
            "def old_function():\n"
            "    pass\n"
        )

        with patch("sylvan.git.run_git", return_value=old_content):
            resp = await get_symbol_diff(repo="diff-repo", file_path="math.py")

        assert "_meta" in resp
        assert resp["summary"]["removed"] >= 1

    async def test_file_path_filter(self, indexed_repo):
        from sylvan.tools.analysis.get_symbol_diff import get_symbol_diff

        with patch("sylvan.git.run_git", return_value=None):
            resp = await get_symbol_diff(repo="diff-repo", file_path="math.py")

        assert "_meta" in resp
        meta = resp["_meta"]
        assert "files_compared" in meta

    async def test_file_not_in_old_commit(self, indexed_repo):
        """When git show returns None, file didn't exist in old commit."""
        from sylvan.tools.analysis.get_symbol_diff import get_symbol_diff

        with patch("sylvan.git.run_git", return_value=None):
            resp = await get_symbol_diff(repo="diff-repo")

        assert "_meta" in resp
        assert resp["summary"]["added"] >= 3


class TestDiffSymbols:
    def test_empty_both(self):
        from sylvan.services.analysis import _diff_symbols

        result = _diff_symbols([], [])
        assert result["added"] == []
        assert result["removed"] == []
        assert result["changed"] == []
        assert result["unchanged_count"] == 0

    def test_all_added(self):
        from sylvan.services.analysis import _diff_symbols

        new = [{"qualified_name": "foo", "kind": "function", "signature": "foo()", "content_hash": "abc"}]
        result = _diff_symbols([], new)
        assert len(result["added"]) == 1
        assert result["added"][0]["qualified_name"] == "foo"

    def test_all_removed(self):
        from sylvan.services.analysis import _diff_symbols

        old = [{"qualified_name": "bar", "kind": "function", "signature": "bar()", "content_hash": "xyz"}]
        result = _diff_symbols(old, [])
        assert len(result["removed"]) == 1

    def test_changed_signature(self):
        from sylvan.services.analysis import _diff_symbols

        old = [{"qualified_name": "f", "kind": "function", "signature": "f(a)", "content_hash": "111"}]
        new = [{"qualified_name": "f", "kind": "function", "signature": "f(a, b)", "content_hash": "222"}]
        result = _diff_symbols(old, new)
        assert len(result["changed"]) == 1
        assert result["changed"][0]["old_signature"] == "f(a)"
        assert result["changed"][0]["new_signature"] == "f(a, b)"
