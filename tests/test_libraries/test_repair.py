"""Tests for sylvan.libraries.repair -- disk scanning, health checking, and data nuking."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.libraries.repair import check_library_health, nuke_library_data, scan_library_disk
from sylvan.session.tracker import SessionTracker


@pytest.fixture
async def repair_ctx(tmp_path):
    """Set up a SylvanContext for repair tests."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
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

    yield backend

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)
    reset_config()


def _make_lib_dir(root, manager, package, version):
    """Create a manager/package/version directory structure."""
    d = root / manager / package / version
    d.mkdir(parents=True)
    return d


async def _insert_library_repo(backend, name, *, manager="pip", package="pkg", version="1.0.0"):
    """Insert a library-type repo directly into the DB."""
    now = datetime.now(UTC).isoformat()
    await backend.execute(
        "INSERT INTO repos (name, source_path, indexed_at, repo_type, "
        "package_manager, package_name, version) "
        "VALUES (?, ?, ?, 'library', ?, ?, ?)",
        [name, None, now, manager, package, version],
    )
    await backend.commit()
    row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", [name])
    return row["id"]


async def _insert_file(backend, repo_id, path="lib.py"):
    """Insert a file record for a repo."""
    await backend.execute(
        "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, 'python', 'hash123', 100)",
        [repo_id, path],
    )
    await backend.commit()
    row = await backend.fetch_one("SELECT id FROM files WHERE repo_id = ? AND path = ?", [repo_id, path])
    return row["id"]


async def _insert_symbol(backend, file_id, symbol_id, name="func"):
    """Insert a symbol record for a file."""
    await backend.execute(
        "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, byte_offset, byte_length) "
        "VALUES (?, ?, ?, ?, 'function', 'python', 0, 10)",
        [file_id, symbol_id, name, name],
    )
    await backend.commit()


class TestScanLibraryDisk:
    def test_empty_dir(self, tmp_path):
        lib_root = tmp_path / "libs"
        lib_root.mkdir()
        result = scan_library_disk(lib_root)
        assert result == []

    def test_nonexistent_dir(self, tmp_path):
        result = scan_library_disk(tmp_path / "does_not_exist")
        assert result == []

    def test_single_library(self, tmp_path):
        lib_root = tmp_path / "libs"
        _make_lib_dir(lib_root, "pip", "django", "4.2.0")

        result = scan_library_disk(lib_root)
        assert len(result) == 1
        assert result[0]["manager"] == "pip"
        assert result[0]["package"] == "django"
        assert result[0]["version"] == "4.2.0"
        assert result[0]["display_name"] == "django@4.2.0"

    def test_multiple_managers(self, tmp_path):
        lib_root = tmp_path / "libs"
        _make_lib_dir(lib_root, "pip", "django", "4.2.0")
        _make_lib_dir(lib_root, "npm", "react", "18.2.0")

        result = scan_library_disk(lib_root)
        assert len(result) == 2
        managers = {r["manager"] for r in result}
        assert managers == {"pip", "npm"}

    def test_npm_scoped_package(self, tmp_path):
        """Scoped packages use -- on disk as separator, restored to / in display."""
        lib_root = tmp_path / "libs"
        _make_lib_dir(lib_root, "npm", "@nuxt--eslint", "0.5.0")

        result = scan_library_disk(lib_root)
        assert len(result) == 1
        assert result[0]["package"] == "@nuxt/eslint"
        assert result[0]["display_name"] == "@nuxt/eslint@0.5.0"

    def test_non_dir_files_ignored(self, tmp_path):
        lib_root = tmp_path / "libs"
        _make_lib_dir(lib_root, "pip", "django", "4.2.0")
        # Create a regular file at the manager level - should be ignored.
        (lib_root / "README.txt").write_text("ignored", encoding="utf-8")
        # Create a regular file at the package level - should be ignored.
        (lib_root / "pip" / "notes.txt").write_text("ignored", encoding="utf-8")

        result = scan_library_disk(lib_root)
        assert len(result) == 1
        assert result[0]["package"] == "django"


class TestCheckLibraryHealth:
    async def test_no_repo_in_db(self, repair_ctx):
        disk = [
            {
                "manager": "pip",
                "package": "django",
                "version": "4.2.0",
                "path": "libs/pip/django/4.2.0",
                "display_name": "django@4.2.0",
            }
        ]
        result = await check_library_health(disk)
        assert len(result) == 1
        assert result[0]["reason"] == "no_repo"

    async def test_repo_exists_no_files(self, repair_ctx):
        await _insert_library_repo(repair_ctx, "django@4.2.0", manager="pip", package="django", version="4.2.0")
        disk = [
            {
                "manager": "pip",
                "package": "django",
                "version": "4.2.0",
                "path": "libs/pip/django/4.2.0",
                "display_name": "django@4.2.0",
            }
        ]
        result = await check_library_health(disk)
        assert len(result) == 1
        assert result[0]["reason"] == "no_files"

    async def test_repo_has_files_no_symbols(self, repair_ctx):
        repo_id = await _insert_library_repo(
            repair_ctx, "django@4.2.0", manager="pip", package="django", version="4.2.0"
        )
        await _insert_file(repair_ctx, repo_id, "models.py")

        disk = [
            {
                "manager": "pip",
                "package": "django",
                "version": "4.2.0",
                "path": "libs/pip/django/4.2.0",
                "display_name": "django@4.2.0",
            }
        ]
        result = await check_library_health(disk)
        assert len(result) == 1
        assert result[0]["reason"] == "no_symbols"

    async def test_stale_prefix(self, repair_ctx):
        repo_id = await _insert_library_repo(
            repair_ctx, "django@4.2.0", manager="pip", package="django", version="4.2.0"
        )
        file_id = await _insert_file(repair_ctx, repo_id, "models.py")
        # Symbol without the expected "django@4.2.0::" prefix.
        await _insert_symbol(repair_ctx, file_id, "models.py::Model#class", name="Model")

        disk = [
            {
                "manager": "pip",
                "package": "django",
                "version": "4.2.0",
                "path": "libs/pip/django/4.2.0",
                "display_name": "django@4.2.0",
            }
        ]
        result = await check_library_health(disk)
        assert len(result) == 1
        assert result[0]["reason"] == "stale_prefix"

    async def test_healthy_library_not_in_result(self, repair_ctx):
        repo_id = await _insert_library_repo(
            repair_ctx, "django@4.2.0", manager="pip", package="django", version="4.2.0"
        )
        file_id = await _insert_file(repair_ctx, repo_id, "models.py")
        # Symbol with the correct prefix.
        await _insert_symbol(repair_ctx, file_id, "django@4.2.0::models.py::Model#class", name="Model")

        disk = [
            {
                "manager": "pip",
                "package": "django",
                "version": "4.2.0",
                "path": "libs/pip/django/4.2.0",
                "display_name": "django@4.2.0",
            }
        ]
        result = await check_library_health(disk)
        assert result == []


class TestNukeLibraryData:
    async def test_nuke_existing_library(self, repair_ctx):
        from sylvan.database.orm import Repo

        repo_id = await _insert_library_repo(
            repair_ctx, "django@4.2.0", manager="pip", package="django", version="4.2.0"
        )
        file_id = await _insert_file(repair_ctx, repo_id, "models.py")
        await _insert_symbol(repair_ctx, file_id, "django@4.2.0::models.py::Model#class", name="Model")

        await nuke_library_data("django@4.2.0")

        repo = await Repo.where(name="django@4.2.0").first()
        assert repo is None

    async def test_nuke_nonexistent_library_no_error(self, repair_ctx):
        # Should not raise.
        await nuke_library_data("nonexistent@0.0.0")
