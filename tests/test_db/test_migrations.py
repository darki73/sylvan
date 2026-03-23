"""Tests for sylvan.database.migrations.runner — migration discovery, execution, rollback."""

from __future__ import annotations

import pytest

from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import (
    _discover_migrations,
    create_migration,
    get_current_version,
    get_pending_migrations,
    rollback_migration,
    run_migrations,
)


@pytest.fixture
async def migration_backend(tmp_path):
    """Create a bare SQLite backend without any schema applied."""
    db_path = tmp_path / "migration_test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    yield backend
    await backend.disconnect()


# ---------------------------------------------------------------------------
# _discover_migrations
# ---------------------------------------------------------------------------

class TestDiscoverMigrations:
    def test_discovers_at_least_one_migration(self):
        migrations = _discover_migrations()
        assert len(migrations) >= 1

    def test_migrations_sorted_by_version(self):
        migrations = _discover_migrations()
        versions = [v for v, _, _ in migrations]
        assert versions == sorted(versions)

    def test_first_migration_is_001(self):
        migrations = _discover_migrations()
        assert migrations[0][0] == 1
        assert "initial_schema" in migrations[0][1]

    def test_migration_modules_have_up_function(self):
        migrations = _discover_migrations()
        for _, name, module in migrations:
            assert hasattr(module, "up"), f"Migration {name} missing up()"


# ---------------------------------------------------------------------------
# get_current_version
# ---------------------------------------------------------------------------

class TestGetCurrentVersion:
    async def test_returns_zero_on_fresh_db(self, migration_backend):
        version = await get_current_version(migration_backend)
        assert version == 0

    async def test_returns_version_after_migration(self, migration_backend):
        await run_migrations(migration_backend)
        version = await get_current_version(migration_backend)
        assert version >= 1


# ---------------------------------------------------------------------------
# get_pending_migrations
# ---------------------------------------------------------------------------

class TestGetPendingMigrations:
    async def test_all_pending_on_fresh_db(self, migration_backend):
        pending = await get_pending_migrations(migration_backend)
        all_migrations = _discover_migrations()
        assert len(pending) == len(all_migrations)

    async def test_none_pending_after_run(self, migration_backend):
        await run_migrations(migration_backend)
        pending = await get_pending_migrations(migration_backend)
        assert len(pending) == 0


# ---------------------------------------------------------------------------
# run_migrations
# ---------------------------------------------------------------------------

class TestRunMigrations:
    async def test_applies_all_migrations(self, migration_backend):
        applied = await run_migrations(migration_backend)
        assert len(applied) >= 1
        assert "001_initial_schema" in applied

    async def test_creates_migration_table(self, migration_backend):
        await run_migrations(migration_backend)
        row = await migration_backend.fetch_value(
            "SELECT COUNT(*) FROM _migrations"
        )
        assert row >= 1

    async def test_idempotent_second_run(self, migration_backend):
        first = await run_migrations(migration_backend)
        second = await run_migrations(migration_backend)
        assert len(first) >= 1
        assert len(second) == 0

    async def test_creates_expected_tables(self, migration_backend):
        await run_migrations(migration_backend)
        tables_rows = await migration_backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in tables_rows}
        assert "repos" in tables
        assert "files" in tables
        assert "symbols" in tables
        assert "sections" in tables
        assert "file_imports" in tables

    async def test_migration_version_tracked(self, migration_backend):
        await run_migrations(migration_backend)
        row = await migration_backend.fetch_one(
            "SELECT version, name FROM _migrations WHERE version = 1"
        )
        assert row is not None
        assert row["name"] == "001_initial_schema"
        assert row["version"] == 1


# ---------------------------------------------------------------------------
# rollback_migration
# ---------------------------------------------------------------------------

class TestRollbackMigration:
    async def test_rollback_on_empty_db_returns_none(self, migration_backend):
        # Ensure migration table exists but no migrations applied
        result = await rollback_migration(migration_backend)
        assert result is None

    async def test_rollback_removes_latest_migration(self, migration_backend):
        await run_migrations(migration_backend)

        all_migrations = _discover_migrations()
        latest_version = max(v for v, _, _ in all_migrations)
        latest_name = next(name for v, name, _ in all_migrations if v == latest_version)

        rolled_back = await rollback_migration(migration_backend)
        assert rolled_back is not None
        assert rolled_back == latest_name

        # The migration record should be removed
        row = await migration_backend.fetch_value(
            "SELECT COUNT(*) FROM _migrations WHERE version = ?",
            [latest_version],
        )
        assert row == 0

    async def test_rollback_decrements_version(self, migration_backend):
        await run_migrations(migration_backend)
        version_before = await get_current_version(migration_backend)

        await rollback_migration(migration_backend)
        version_after = await get_current_version(migration_backend)

        assert version_after < version_before

    async def test_rollback_then_reapply(self, migration_backend):
        await run_migrations(migration_backend)
        await rollback_migration(migration_backend)

        # Re-apply should work
        applied = await run_migrations(migration_backend)
        assert len(applied) >= 1


# ---------------------------------------------------------------------------
# create_migration
# ---------------------------------------------------------------------------

class TestCreateMigration:
    def test_creates_migration_file(self, tmp_path, monkeypatch):
        from sylvan.database.migrations import runner
        monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)

        filepath = create_migration("add user roles")
        assert filepath.exists()
        # Empty dir -> next version is 1
        assert filepath.name.startswith("001_")
        assert "add_user_roles" in filepath.name

        content = filepath.read_text(encoding="utf-8")
        assert "async def up" in content
        assert "async def down" in content
        assert "add user roles" in content

    def test_sanitizes_description(self, tmp_path, monkeypatch):
        from sylvan.database.migrations import runner
        monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)

        filepath = create_migration("Add User-Roles & Perms!")
        # Should not contain special characters in filename
        assert "&" not in filepath.name
        assert "!" not in filepath.name
        assert filepath.exists()
