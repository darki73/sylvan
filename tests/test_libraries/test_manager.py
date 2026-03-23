"""Tests for the library manager (async orchestration).

Covers:
- sylvan.libraries.manager (async_add_library, async_remove_library, async_list_libraries)
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.libraries.resolution.package_registry import PackageInfo
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def mgr_ctx(tmp_path):
    """Set up a SylvanContext for library manager tests."""
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
    reset_config()


async def _insert_library_repo(backend, name, *, manager="pip", package="pkg",
                                version="1.0.0"):
    """Insert a library-type repo directly into the DB."""
    await backend.execute(
        "INSERT INTO repos (name, source_path, indexed_at, repo_type, "
        "package_manager, package_name, version) "
        "VALUES (?, ?, datetime('now'), 'library', ?, ?, ?)",
        [name, None, manager, package, version],
    )
    await backend.commit()
    row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", [name])
    return row["id"]


# ---------------------------------------------------------------------------
# async_add_library
# ---------------------------------------------------------------------------

class TestAsyncAddLibrary:
    async def test_success(self, mgr_ctx, tmp_path):
        from sylvan.libraries.manager import async_add_library

        fake_info = PackageInfo(
            name="django",
            version="4.2.7",
            repo_url="https://github.com/django/django",
            tag="4.2.7",
            manager="pip",
        )

        mock_result = MagicMock()
        mock_result.files_indexed = 100
        mock_result.symbols_extracted = 500
        mock_result.sections_extracted = 50
        mock_result.duration_ms = 1234

        with (
            patch("sylvan.libraries.manager.resolve", return_value=fake_info),
            patch("sylvan.libraries.manager.fetch_source", return_value=tmp_path / "src"),
            patch(
                "sylvan.indexing.pipeline.orchestrator.index_folder",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result = await async_add_library("pip/django@4.2")

        assert result["status"] == "indexed"
        assert result["name"] == "django@4.2.7"
        assert result["files_indexed"] == 100
        assert result["symbols_extracted"] == 500

    async def test_already_indexed(self, mgr_ctx):
        from sylvan.libraries.manager import async_add_library

        backend = mgr_ctx
        await _insert_library_repo(backend, "django@4.2.7", package="django", version="4.2.7")

        fake_info = PackageInfo(
            name="django",
            version="4.2.7",
            repo_url="https://github.com/django/django",
            tag="4.2.7",
            manager="pip",
        )

        with patch("sylvan.libraries.manager.resolve", return_value=fake_info):
            result = await async_add_library("pip/django@4.2")

        assert result["status"] == "already_indexed"
        assert "already indexed" in result["message"]


# ---------------------------------------------------------------------------
# async_remove_library
# ---------------------------------------------------------------------------

class TestAsyncRemoveLibrary:
    async def test_remove_existing(self, mgr_ctx):
        from sylvan.libraries.manager import async_remove_library

        backend = mgr_ctx
        await _insert_library_repo(
            backend, "django@4.2", manager="pip", package="django", version="4.2"
        )

        with patch("sylvan.libraries.manager.remove_library_source"):
            result = await async_remove_library("django@4.2")

        assert result["status"] == "removed"
        assert result["name"] == "django@4.2"

    async def test_remove_not_found(self, mgr_ctx):
        from sylvan.libraries.manager import async_remove_library

        result = await async_remove_library("nonexistent@1.0")
        assert result["status"] == "not_found"

    async def test_remove_fuzzy_match(self, mgr_ctx):
        from sylvan.libraries.manager import async_remove_library

        backend = mgr_ctx
        await _insert_library_repo(
            backend, "django@4.2", manager="pip", package="django", version="4.2"
        )

        with patch("sylvan.libraries.manager.remove_library_source"):
            result = await async_remove_library("django")

        assert result["status"] == "removed"

    async def test_remove_without_package_info(self, mgr_ctx):
        """Repos without package_manager/name/version skip source removal."""
        from sylvan.libraries.manager import async_remove_library

        backend = mgr_ctx
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at, repo_type) "
            "VALUES (?, ?, datetime('now'), 'library')",
            ["orphan-lib", None],
        )
        await backend.commit()

        with patch("sylvan.libraries.manager.remove_library_source") as mock_rm:
            result = await async_remove_library("orphan-lib")

        assert result["status"] == "removed"
        mock_rm.assert_not_called()


# ---------------------------------------------------------------------------
# async_list_libraries
# ---------------------------------------------------------------------------

class TestAsyncListLibraries:
    async def test_empty_list(self, mgr_ctx):
        from sylvan.libraries.manager import async_list_libraries

        result = await async_list_libraries()
        assert result == []

    async def test_lists_libraries(self, mgr_ctx):
        from sylvan.libraries.manager import async_list_libraries

        backend = mgr_ctx
        await _insert_library_repo(
            backend, "numpy@1.25", manager="pip", package="numpy", version="1.25"
        )
        await _insert_library_repo(
            backend, "pandas@2.0", manager="pip", package="pandas", version="2.0"
        )

        result = await async_list_libraries()
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "numpy@1.25" in names
        assert "pandas@2.0" in names

    async def test_list_includes_metadata(self, mgr_ctx):
        from sylvan.libraries.manager import async_list_libraries

        backend = mgr_ctx
        repo_id = await _insert_library_repo(
            backend, "django@4.2", manager="pip", package="django", version="4.2"
        )

        # Add a file and symbol to verify counts
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) "
            "VALUES (?, 'mod.py', 'python', 'abc', 100)",
            [repo_id],
        )
        await backend.commit()
        file_row = await backend.fetch_one(
            "SELECT id FROM files WHERE repo_id = ?", [repo_id]
        )
        await backend.execute(
            "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, "
            "language, signature, line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, 'sym1', 'func', 'mod.func', 'function', 'python', '', 1, 10, 0, 50)",
            [file_row["id"]],
        )
        await backend.commit()

        result = await async_list_libraries()
        assert len(result) == 1
        lib = result[0]
        assert lib["name"] == "django@4.2"
        assert lib["manager"] == "pip"
        assert lib["package"] == "django"
        assert lib["version"] == "4.2"
        assert lib["symbols"] == 1
