"""Tests for library tool handlers and workspace pin_library.

Covers:
- sylvan.tools.library.add
- sylvan.tools.library.list
- sylvan.tools.library.remove
- sylvan.tools.library.check
- sylvan.tools.library.compare
- sylvan.tools.workspace.pin_library
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def lib_ctx(tmp_path):
    """Set up a SylvanContext with schema ready for library tests."""
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

    yield backend

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


async def _insert_library_repo(backend, name, *, manager="pip", package="pkg", version="1.0.0", source_path=None):
    """Helper to insert a library-type repo directly into the DB."""
    await backend.execute(
        "INSERT INTO repos (name, source_path, indexed_at, repo_type, "
        "package_manager, package_name, version) "
        "VALUES (?, ?, datetime('now'), 'library', ?, ?, ?)",
        [name, source_path, manager, package, version],
    )
    await backend.commit()
    row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", [name])
    return row["id"]


async def _insert_local_repo(backend, name, source_path=None):
    """Helper to insert a local-type repo."""
    await backend.execute(
        "INSERT INTO repos (name, source_path, indexed_at, repo_type) VALUES (?, ?, datetime('now'), 'local')",
        [name, source_path],
    )
    await backend.commit()
    row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", [name])
    return row["id"]


async def _insert_symbol(backend, file_id, symbol_id, name, qualified_name, kind="function", signature=""):
    """Helper to insert a symbol."""
    await backend.execute(
        "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, "
        "language, signature, line_start, line_end, byte_offset, byte_length) "
        "VALUES (?, ?, ?, ?, ?, 'python', ?, 1, 10, 0, 100)",
        [file_id, symbol_id, name, qualified_name, kind, signature],
    )
    await backend.commit()


async def _insert_file(backend, repo_id, path="mod.py", language="python"):
    """Helper to insert a file record."""
    await backend.execute(
        "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, 'abc123', 100)",
        [repo_id, path, language],
    )
    await backend.commit()
    row = await backend.fetch_one("SELECT id FROM files WHERE repo_id = ? AND path = ?", [repo_id, path])
    return row["id"]


# ---------------------------------------------------------------------------
# add_library
# ---------------------------------------------------------------------------


class TestAddLibrary:
    async def test_success_delegates_to_manager(self, lib_ctx):
        from sylvan.tools.library.add import add_library

        mock_result = {"status": "indexed", "name": "django@4.2"}
        with patch(
            "sylvan.libraries.manager.async_add_library",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await add_library(package="pip/django@4.2")

        assert "_meta" in resp
        assert resp["status"] == "indexed"

    async def test_value_error_returns_error_dict(self, lib_ctx):
        from sylvan.tools.library.add import add_library

        with patch(
            "sylvan.libraries.manager.async_add_library",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid package spec"),
        ):
            resp = await add_library(package="badspec")

        assert "error" in resp
        assert "Invalid package spec" in resp["error"]

    async def test_generic_exception_returns_error_dict(self, lib_ctx):
        from sylvan.tools.library.add import add_library

        with patch(
            "sylvan.libraries.manager.async_add_library",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network down"),
        ):
            resp = await add_library(package="pip/django@4.2")

        assert "error" in resp
        assert "Failed to add library" in resp["error"]


# ---------------------------------------------------------------------------
# list_libraries
# ---------------------------------------------------------------------------


class TestListLibraries:
    async def test_empty_list(self, lib_ctx):
        from sylvan.tools.library.list import list_libraries

        resp = await list_libraries()
        assert "_meta" in resp
        assert resp["libraries"] == []
        assert resp["_meta"]["results_count"] == 0

    async def test_lists_indexed_libraries(self, lib_ctx):
        backend = lib_ctx
        await _insert_library_repo(backend, "numpy@1.25.0", package="numpy", version="1.25.0")
        await _insert_library_repo(backend, "pandas@2.0.0", package="pandas", version="2.0.0")

        from sylvan.tools.library.list import list_libraries

        resp = await list_libraries()
        assert resp["_meta"]["results_count"] == 2
        names = [lib["name"] for lib in resp["libraries"]]
        assert "numpy@1.25.0" in names
        assert "pandas@2.0.0" in names


# ---------------------------------------------------------------------------
# remove_library
# ---------------------------------------------------------------------------


class TestRemoveLibrary:
    async def test_remove_existing(self, lib_ctx):
        backend = lib_ctx
        await _insert_library_repo(backend, "django@4.2", package="django", version="4.2")

        from sylvan.tools.library.remove import remove_library

        with patch("sylvan.libraries.source_fetcher.remove_library_source"):
            resp = await remove_library(name="django@4.2")

        assert "_meta" in resp
        assert resp["status"] == "removed"

    async def test_remove_not_found(self, lib_ctx):
        from sylvan.tools.library.remove import remove_library

        resp = await remove_library(name="nonexistent@1.0")
        assert resp["status"] == "not_found"


# ---------------------------------------------------------------------------
# check_library_versions
# ---------------------------------------------------------------------------


class TestCheckLibraryVersions:
    async def test_repo_not_found(self, lib_ctx):
        from sylvan.tools.library.check import check_library_versions

        resp = await check_library_versions(repo="nonexistent")
        assert "error" in resp

    async def test_no_dependency_files(self, lib_ctx, tmp_path):
        backend = lib_ctx
        proj = tmp_path / "myproject"
        proj.mkdir()
        await _insert_local_repo(backend, "myproject", source_path=str(proj))

        from sylvan.tools.library.check import check_library_versions

        resp = await check_library_versions(repo="myproject")
        assert "message" in resp
        assert resp["outdated"] == []
        assert resp["up_to_date"] == []
        assert resp["not_indexed"] == []

    async def test_deps_classified_correctly(self, lib_ctx, tmp_path):
        backend = lib_ctx

        # Create project with a requirements.txt
        proj = tmp_path / "checkproject"
        proj.mkdir()
        (proj / "requirements.txt").write_text(
            "numpy==1.25.0\npandas==2.0.0\nrequests==2.31.0\n",
            encoding="utf-8",
        )
        await _insert_local_repo(backend, "checkproject", source_path=str(proj))

        # parse_dependencies returns version strings like "==1.25.0" from
        # requirements.txt.  The check tool compares dep["version"] against
        # indexed Repo.version values, so we need to match the parsed format.
        from sylvan.git.dependency_files import parse_dependencies

        parsed = parse_dependencies(proj)
        numpy_ver = next(d["version"] for d in parsed if d["name"] == "numpy")

        # Index numpy at matching version, pandas at different version
        await _insert_library_repo(backend, f"numpy@{numpy_ver}", package="numpy", version=numpy_ver, manager="pip")
        await _insert_library_repo(backend, "pandas@1.5.0", package="pandas", version="1.5.0", manager="pip")

        from sylvan.tools.library.check import check_library_versions

        resp = await check_library_versions(repo="checkproject")
        assert "_meta" in resp

        up_to_date_names = [d["name"] for d in resp["up_to_date"]]
        outdated_names = [d["name"] for d in resp["outdated"]]
        not_indexed_names = [d["name"] for d in resp["not_indexed"]]

        assert "numpy" in up_to_date_names
        assert "pandas" in outdated_names
        assert "requests" in not_indexed_names

        assert resp["_meta"]["total_deps"] == 3


# ---------------------------------------------------------------------------
# compare_library_versions
# ---------------------------------------------------------------------------


class TestCompareLibraryVersions:
    async def test_old_version_not_indexed(self, lib_ctx):
        from sylvan.tools.library.compare import compare_library_versions

        resp = await compare_library_versions(package="numpy", from_version="1.0", to_version="2.0")
        assert "error" in resp
        assert "numpy@1.0" in resp["error"]

    async def test_new_version_not_indexed(self, lib_ctx):
        backend = lib_ctx
        await _insert_library_repo(backend, "numpy@1.0", package="numpy", version="1.0")

        from sylvan.tools.library.compare import compare_library_versions

        resp = await compare_library_versions(package="numpy", from_version="1.0", to_version="2.0")
        assert "error" in resp
        assert "numpy@2.0" in resp["error"]

    async def test_compare_detects_added_removed_changed(self, lib_ctx):
        backend = lib_ctx

        old_id = await _insert_library_repo(backend, "mylib@1.0", package="mylib", version="1.0")
        new_id = await _insert_library_repo(backend, "mylib@2.0", package="mylib", version="2.0")

        old_file = await _insert_file(backend, old_id, "lib.py")
        new_file = await _insert_file(backend, new_id, "lib.py")

        # Old version has: func_a (will be removed), func_b (will change sig)
        await _insert_symbol(
            backend,
            old_file,
            "old::func_a#function",
            "func_a",
            "lib.func_a",
            kind="function",
            signature="def func_a(x)",
        )
        await _insert_symbol(
            backend,
            old_file,
            "old::func_b#function",
            "func_b",
            "lib.func_b",
            kind="function",
            signature="def func_b(x)",
        )

        # New version has: func_b (changed sig), func_c (added)
        await _insert_symbol(
            backend,
            new_file,
            "new::func_b#function",
            "func_b",
            "lib.func_b",
            kind="function",
            signature="def func_b(x, y)",
        )
        await _insert_symbol(
            backend, new_file, "new::func_c#function", "func_c", "lib.func_c", kind="function", signature="def func_c()"
        )

        from sylvan.tools.library.compare import compare_library_versions

        resp = await compare_library_versions(package="mylib", from_version="1.0", to_version="2.0")

        assert resp["package"] == "mylib"
        assert resp["from_version"] == "1.0"
        assert resp["to_version"] == "2.0"

        added_names = [s["qualified_name"] for s in resp["added"]]
        removed_names = [s["qualified_name"] for s in resp["removed"]]
        changed_names = [s["qualified_name"] for s in resp["changed"]]

        assert "lib.func_c" in added_names
        assert "lib.func_a" in removed_names
        assert "lib.func_b" in changed_names

        assert resp["summary"]["breaking_risk"] == "high"
        assert resp["_meta"]["added_count"] == 1
        assert resp["_meta"]["removed_count"] == 1
        assert resp["_meta"]["changed_count"] == 1

    async def test_compare_identical_versions(self, lib_ctx):
        backend = lib_ctx

        v1_id = await _insert_library_repo(backend, "same@1.0", package="same", version="1.0")
        v2_id = await _insert_library_repo(backend, "same@2.0", package="same", version="2.0")

        f1 = await _insert_file(backend, v1_id, "lib.py")
        f2 = await _insert_file(backend, v2_id, "lib.py")

        await _insert_symbol(backend, f1, "v1::foo#function", "foo", "lib.foo", kind="function", signature="def foo()")
        await _insert_symbol(backend, f2, "v2::foo#function", "foo", "lib.foo", kind="function", signature="def foo()")

        from sylvan.tools.library.compare import compare_library_versions

        resp = await compare_library_versions(package="same", from_version="1.0", to_version="2.0")

        assert resp["added"] == []
        assert resp["removed"] == []
        assert resp["changed"] == []
        assert resp["summary"]["breaking_risk"] == "low"


# ---------------------------------------------------------------------------
# pin_library (workspace tool)
# ---------------------------------------------------------------------------


class TestPinLibrary:
    async def test_workspace_not_found(self, lib_ctx):
        from sylvan.error_codes import WorkspaceNotFoundError
        from sylvan.tools.workspace.pin_library import pin_library

        with pytest.raises(WorkspaceNotFoundError):
            await pin_library(workspace="nonexistent", library="numpy@2.0")

    async def test_library_not_indexed(self, lib_ctx):
        backend = lib_ctx
        # Create workspace
        await backend.execute(
            "INSERT INTO workspaces (name, description) VALUES (?, ?)",
            ["my-ws", "test workspace"],
        )
        await backend.commit()

        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.workspace.pin_library import pin_library

        with pytest.raises(RepoNotFoundError):
            await pin_library(workspace="my-ws", library="notindexed@1.0")

    async def test_pin_success(self, lib_ctx):
        backend = lib_ctx

        # Create workspace
        await backend.execute(
            "INSERT INTO workspaces (name, description) VALUES (?, ?)",
            ["my-ws", "test workspace"],
        )
        await backend.commit()

        # Insert library repo
        await _insert_library_repo(backend, "numpy@2.0", package="numpy", version="2.0")

        from sylvan.tools.workspace.pin_library import pin_library

        resp = await pin_library(workspace="my-ws", library="numpy@2.0")

        assert resp["status"] == "pinned"
        assert resp["workspace"] == "my-ws"
        assert resp["library"] == "numpy@2.0"
        assert resp["_meta"]["workspace"] == "my-ws"

        # Verify DB state
        rows = await backend.fetch_all(
            "SELECT repo_id FROM workspace_repos WHERE workspace_id = (SELECT id FROM workspaces WHERE name = 'my-ws')",
            [],
        )
        assert len(rows) == 1
