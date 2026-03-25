"""Tests for sylvan.tools misc — search_text, get_context_bundle, get_git_context."""

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
    """Index a sample project with importable files."""
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
        "from util import helper\n"
        "\n"
        "def greet(name):\n"
        '    """Greet someone."""\n'
        '    return f"Hello {name}"\n'
        "\n"
        "def farewell(name):\n"
        '    return f"Goodbye {name}"\n',
        encoding="utf-8",
    )
    (proj / "util.py").write_text(
        'def helper():\n    """A helpful utility."""\n    pass\n\ndef another_helper():\n    pass\n',
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


async def _find_symbol_id(name):
    """Find a symbol ID by name."""
    from sylvan.tools.search.search_symbols import search_symbols

    resp = await search_symbols(query=name)
    for s in resp["symbols"]:
        if s["name"] == name:
            return s["symbol_id"]
    raise AssertionError(f"Symbol '{name}' not found")


class TestSearchText:
    async def test_finds_matches(self, indexed_repo):
        from sylvan.tools.search.search_text import search_text

        resp = await search_text(query="Hello")

        assert "matches" in resp
        assert "_meta" in resp
        assert "results_count" in resp["_meta"]
        assert "query" in resp["_meta"]
        assert resp["_meta"]["query"] == "Hello"

        matches = resp["matches"]
        assert isinstance(matches, list)
        assert len(matches) >= 1

        m = matches[0]
        assert "file_path" in m
        assert "line" in m
        assert "match" in m
        assert "context" in m

    async def test_no_matches_returns_empty(self, indexed_repo):
        from sylvan.tools.search.search_text import search_text

        resp = await search_text(query="zzzznonexistenttext")

        assert "matches" in resp
        assert resp["matches"] == []
        assert resp["_meta"]["results_count"] == 0

    async def test_filter_by_repo(self, indexed_repo):
        from sylvan.tools.search.search_text import search_text

        resp = await search_text(query="helper", repo="test-repo")

        assert "matches" in resp
        assert len(resp["matches"]) >= 1
        for m in resp["matches"]:
            assert m["repo_name"] == "test-repo"


class TestGetContextBundle:
    async def test_returns_symbol_plus_siblings_and_imports(self, indexed_repo):
        from sylvan.tools.browsing.get_context_bundle import get_context_bundle

        sid = await _find_symbol_id("greet")
        resp = await get_context_bundle(sid)

        assert "_meta" in resp
        assert "symbol" in resp
        sym = resp["symbol"]
        assert sym["name"] == "greet"
        assert "source" in sym
        assert "signature" in sym
        assert "docstring" in sym

        assert "siblings" in resp
        assert isinstance(resp["siblings"], list)
        sibling_names = [s["name"] for s in resp["siblings"]]
        assert "farewell" in sibling_names

        assert "imports" in resp
        assert isinstance(resp["imports"], list)

        meta = resp["_meta"]
        assert "has_imports" in meta
        assert "siblings_count" in meta

    async def test_symbol_not_found(self, indexed_repo):
        from sylvan.error_codes import SymbolNotFoundError
        from sylvan.tools.browsing.get_context_bundle import get_context_bundle

        with pytest.raises(SymbolNotFoundError) as exc_info:
            await get_context_bundle("nonexistent::sym#function")

        resp = exc_info.value.to_dict()
        assert "_meta" in resp
        assert resp["error"] == "symbol_not_found"

    async def test_without_imports(self, indexed_repo):
        from sylvan.tools.browsing.get_context_bundle import get_context_bundle

        sid = await _find_symbol_id("greet")
        resp = await get_context_bundle(sid, include_imports=False)

        assert "symbol" in resp
        assert "imports" not in resp


class TestGetGitContext:
    async def test_non_git_repo_returns_graceful_error(self, indexed_repo):
        """A non-git indexed folder should return a graceful error."""
        from sylvan.tools.analysis.get_git_context import get_git_context

        resp = await get_git_context(repo="test-repo", file_path="main.py")

        assert "_meta" in resp
        assert isinstance(resp, dict)

    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.analysis.get_git_context import get_git_context

        with pytest.raises(RepoNotFoundError):
            await get_git_context(repo="nonexistent-repo", file_path="main.py")

    async def test_no_file_or_symbol_returns_error(self, indexed_repo):
        from sylvan.tools.analysis.get_git_context import get_git_context

        resp = await get_git_context(repo="test-repo")

        assert "_meta" in resp
        assert "error" in resp
        assert "provide" in resp["error"]


class TestFindImportersHasImporters:
    async def test_has_importers_flag_present(self, indexed_repo):
        """Files that are themselves imported should have has_importers=True."""
        # Re-index a fresh project with explicit imports
        from sylvan.context import get_context

        ctx = get_context()
        backend = ctx.backend

        proj = indexed_repo  # We already have a context; create a new project in it
        # Use a separate tmp dir for this test's project
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            from pathlib import Path

            proj = Path(td)
            (proj / "a.py").write_text("from b import foo\n", encoding="utf-8")
            (proj / "b.py").write_text("def foo(): pass\n", encoding="utf-8")
            (proj / "c.py").write_text("from a import something\n", encoding="utf-8")

            from sylvan.indexing.pipeline.orchestrator import index_folder

            await index_folder(str(proj), name="imp-test")
            await backend.commit()

            # Resolve imports so resolved_file_id is populated
            from sylvan.database.orm.models import FileImport, FileRecord, Repo

            imp_repo = await Repo.where(name="imp-test").first()
            files_list = await FileRecord.where(repo_id=imp_repo.id).get()
            imp_test_files = {f.path: f.id for f in files_list}

            all_imports = await FileImport.query().get()
            for imp in all_imports:
                imp_file = await FileRecord.find(imp.file_id)
                if imp_file and imp_file.path == "a.py" and imp.specifier == "b":
                    await backend.execute(
                        "UPDATE file_imports SET resolved_file_id=? WHERE id=?",
                        [imp_test_files.get("b.py"), imp.id],
                    )
                elif imp_file and imp_file.path == "c.py" and imp.specifier == "a":
                    await backend.execute(
                        "UPDATE file_imports SET resolved_file_id=? WHERE id=?",
                        [imp_test_files.get("a.py"), imp.id],
                    )
            await backend.commit()

            from sylvan.tools.analysis.find_importers import find_importers

            resp = await find_importers(repo="imp-test", file_path="b.py")
            assert len(resp["importers"]) >= 1
            for imp in resp["importers"]:
                assert "has_importers" in imp


class TestIndexFolderPathGuard:
    async def test_rejects_broad_path(self, indexed_repo):
        from sylvan.error_codes import PathTooBroadError
        from sylvan.tools.indexing.index_folder import index_folder

        with pytest.raises(PathTooBroadError):
            await index_folder("/")

    async def test_accepts_deep_path(self, tmp_path, indexed_repo):
        proj = tmp_path / "deep" / "project"
        proj.mkdir(parents=True)
        (proj / "app.py").write_text("x = 1\n", encoding="utf-8")

        from sylvan.tools.indexing.index_folder import index_folder

        result = await index_folder(str(proj))
        assert result.get("files_indexed", 0) >= 1
