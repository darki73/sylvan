"""Tests for schema creation via migrations — tables, FTS5, vec tables, migration tracking."""

from __future__ import annotations

import os

from sylvan.config import reset_config
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import get_current_version, run_migrations


async def _make_backend(tmp_path):
    """Create an async backend and run migrations."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    reset_config()
    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)
    return backend


class TestRunMigrations:
    """Tests for schema creation via run_migrations()."""

    async def test_creates_repos_table(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            rows = await backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r["name"] for r in rows}
            assert "repos" in tables
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_files_table(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            rows = await backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r["name"] for r in rows}
            assert "files" in tables
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_symbols_table(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            rows = await backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r["name"] for r in rows}
            assert "symbols" in tables
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_blobs_table(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            rows = await backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r["name"] for r in rows}
            assert "blobs" in tables
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_sections_table(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            rows = await backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r["name"] for r in rows}
            assert "sections" in tables
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_usage_stats_table(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            rows = await backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r["name"] for r in rows}
            assert "usage_stats" in tables
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_fts5_symbols_fts(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            row = await backend.fetch_one("SELECT name FROM sqlite_master WHERE name='symbols_fts'")
            assert row is not None
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_fts5_sections_fts(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            row = await backend.fetch_one("SELECT name FROM sqlite_master WHERE name='sections_fts'")
            assert row is not None
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_vec_tables(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            row = await backend.fetch_one("SELECT name FROM sqlite_master WHERE name='symbols_vec'")
            assert row is not None
            row2 = await backend.fetch_one("SELECT name FROM sqlite_master WHERE name='sections_vec'")
            assert row2 is not None
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_migration_version_recorded(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            version = await get_current_version(backend)
            assert version >= 1
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_idempotent_migration(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            # Second run should not raise
            await run_migrations(backend)
            version = await get_current_version(backend)
            assert version >= 1
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_file_imports_table(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            rows = await backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r["name"] for r in rows}
            assert "file_imports" in tables
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)

    async def test_creates_indexes(self, tmp_path):
        backend = await _make_backend(tmp_path)
        try:
            rows = await backend.fetch_all("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {r["name"] for r in rows}
            assert "idx_symbols_file_id" in indexes
            assert "idx_symbols_kind" in indexes
            assert "idx_files_repo_id" in indexes
        finally:
            await backend.disconnect()
            os.environ.pop("SYLVAN_HOME", None)
