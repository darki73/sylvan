"""Tests for sylvan.tools repo tools — file outline, file tree, list repos, etc."""

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
    """Index a multi-file project."""
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
    sub = proj / "pkg"
    sub.mkdir()
    (proj / "main.py").write_text(
        "def main():\n"
        '    """Entry point."""\n'
        "    pass\n"
        "\n"
        "class App:\n"
        "    def run(self):\n"
        "        pass\n"
        "    def stop(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    (sub / "util.py").write_text(
        "def helper():\n    pass\n\ndef format_output(data):\n    pass\n",
        encoding="utf-8",
    )
    (proj / "README.md").write_text(
        "# Test Project\n\nA test project.\n\n## Setup\n\nRun setup.\n",
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()
    assert result.files_indexed >= 2

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


class TestGetFileOutline:
    async def test_returns_hierarchical_structure(self, indexed_repo):
        from sylvan.tools.browsing.get_file_outline import GetFileOutline

        resp = await GetFileOutline().execute({"repo": "test-repo", "file_path": "main.py"})

        assert "outline" in resp
        assert "file" in resp
        assert resp["file"] == "main.py"
        assert "_meta" in resp
        assert "symbol_count" in resp["_meta"]

        outline = resp["outline"]
        assert isinstance(outline, list)
        assert len(outline) >= 2

        node = outline[0]
        assert "symbol_id" in node
        assert "name" in node
        assert "kind" in node
        assert "children" in node
        assert isinstance(node["children"], list)

        app_nodes = [n for n in outline if n["name"] == "App"]
        if app_nodes:
            assert len(app_nodes[0]["children"]) >= 2

    async def test_nonexistent_file_raises_file_not_found(self, indexed_repo):
        from sylvan.error_codes import IndexFileNotFoundError
        from sylvan.tools.browsing.get_file_outline import GetFileOutline

        with pytest.raises(IndexFileNotFoundError) as exc_info:
            await GetFileOutline().execute({"repo": "test-repo", "file_path": "nonexistent.py"})

        resp = exc_info.value.to_dict()
        assert resp["error"] == "file_not_found"


class TestGetFileTree:
    async def test_returns_directory_tree(self, indexed_repo):
        from sylvan.tools.browsing.get_file_tree import GetFileTree

        resp = await GetFileTree().execute({"repo": "test-repo"})

        assert "tree" in resp
        assert "_meta" in resp
        assert resp["_meta"]["repo"] == "test-repo"

        tree = resp["tree"]
        assert isinstance(tree, str)
        assert "test-repo/" in tree
        assert "main.py" in tree
        assert "[python" in tree


class TestListRepos:
    async def test_returns_indexed_repos(self, indexed_repo):
        from sylvan.tools.meta.list_repos import list_repos

        resp = await list_repos()

        assert "repos" in resp
        assert "_meta" in resp
        assert "results_count" in resp["_meta"]
        assert resp["_meta"]["results_count"] >= 1

        repos = resp["repos"]
        assert isinstance(repos, list)
        assert len(repos) >= 1

        repo_names = [r["name"] for r in repos]
        assert "test-repo" in repo_names


class TestGetRepoOutline:
    async def test_shows_languages_and_kinds(self, indexed_repo):
        from sylvan.tools.browsing.get_repo_outline import GetRepoOutline

        resp = await GetRepoOutline().execute({"repo": "test-repo"})

        assert "_meta" in resp
        assert "repo" in resp
        assert resp["repo"] == "test-repo"
        assert "files" in resp
        assert "symbols" in resp
        assert "languages" in resp
        assert "symbol_kinds" in resp
        assert isinstance(resp["languages"], dict)
        assert isinstance(resp["symbol_kinds"], dict)

        assert "python" in resp["languages"]
        assert resp["files"] >= 2
        assert resp["symbols"] >= 4

        assert "function" in resp["symbol_kinds"] or "method" in resp["symbol_kinds"]

    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.browsing.get_repo_outline import GetRepoOutline

        with pytest.raises(RepoNotFoundError):
            await GetRepoOutline().execute({"repo": "nonexistent-repo"})


class TestSuggestQueries:
    async def test_returns_suggestions(self, indexed_repo):
        from sylvan.tools.meta.suggest_queries import suggest_queries

        resp = await suggest_queries(repo="test-repo")

        assert "suggestions" in resp
        assert "_meta" in resp
        assert "suggestion_count" in resp["_meta"]

        suggestions = resp["suggestions"]
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 1

        for s in suggestions:
            assert "query" in s
            assert "reason" in s
            assert "tool" in s

    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.meta.suggest_queries import suggest_queries

        with pytest.raises(RepoNotFoundError):
            await suggest_queries(repo="nonexistent-repo")
