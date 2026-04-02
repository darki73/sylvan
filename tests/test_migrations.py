"""Tests for sylvan.database.migrations.runner — async migration discovery and execution."""

import importlib.util
import textwrap
from unittest.mock import patch

from sylvan.database.migrations.runner import (
    create_migration,
    get_current_version,
    rollback_migration,
    run_migrations,
)


class TestGetCurrentVersion:
    async def test_returns_initial_version_after_migrations(self, ctx):
        """Database has all discovered migrations applied from backend fixture.

        Returns:
            None.
        """
        version = await get_current_version(ctx.backend)
        assert version == 5

    async def test_returns_max_applied_version(self, ctx):
        """Returns the highest version from the _migrations table.

        Returns:
            None.
        """
        await ctx.backend.execute(
            "INSERT INTO _migrations (version, name, applied_at) VALUES (?, ?, ?)",
            [6, "006_add_col", "2024-01-02"],
        )
        await ctx.backend.commit()
        assert await get_current_version(ctx.backend) == 6


class TestRunMigrations:
    async def test_applies_pending_migrations(self, ctx, tmp_path):
        """Applies all pending migration modules in order.

        Returns:
            None.
        """
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        # Use version numbers above 005 (already applied by backend fixture)
        (mig_dir / "006_create_widgets.py").write_text(
            textwrap.dedent("""\
            async def up(backend, dialect):
                await backend.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
            async def down(backend, dialect):
                await backend.execute("DROP TABLE widgets")
        """),
            encoding="utf-8",
        )

        (mig_dir / "007_add_color.py").write_text(
            textwrap.dedent("""\
            async def up(backend, dialect):
                await backend.execute("ALTER TABLE widgets ADD COLUMN color TEXT")
            async def down(backend, dialect):
                pass
        """),
            encoding="utf-8",
        )

        def fake_discover():
            results = []
            for f in sorted(mig_dir.glob("[0-9][0-9][0-9]_*.py")):
                stem = f.stem
                version = int(stem.split("_", 1)[0])
                spec = importlib.util.spec_from_file_location(stem, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                results.append((version, stem, mod))
            return results

        with patch("sylvan.database.migrations.runner._discover_migrations", fake_discover):
            applied = await run_migrations(ctx.backend)

        assert len(applied) == 2
        assert "006_create_widgets" in applied[0]
        assert await get_current_version(ctx.backend) == 7

        row = await ctx.backend.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name='widgets'")
        assert row is not None

    async def test_returns_empty_when_nothing_pending(self, ctx):
        """Returns an empty list when all migrations are applied.

        Returns:
            None.
        """
        with patch("sylvan.database.migrations.runner._discover_migrations", return_value=[]):
            applied = await run_migrations(ctx.backend)
        assert applied == []


class TestRollbackMigration:
    async def test_rollback_reverses_last(self, ctx, tmp_path):
        """Rolls back the most recent migration.

        Returns:
            None.
        """
        # Add a migration manually so we can test rolling it back.
        await ctx.backend.execute("CREATE TABLE gadgets (id INTEGER PRIMARY KEY)")
        await ctx.backend.execute(
            "INSERT INTO _migrations (version, name, applied_at) VALUES (?, ?, ?)",
            [6, "006_create_gadgets", "2024-01-01"],
        )
        await ctx.backend.commit()

        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "006_create_gadgets.py").write_text(
            textwrap.dedent("""\
            async def up(backend, dialect):
                await backend.execute("CREATE TABLE gadgets (id INTEGER PRIMARY KEY)")
            async def down(backend, dialect):
                await backend.execute("DROP TABLE gadgets")
        """),
            encoding="utf-8",
        )

        def fake_discover():
            results = []
            for f in sorted(mig_dir.glob("[0-9][0-9][0-9]_*.py")):
                stem = f.stem
                version = int(stem.split("_", 1)[0])
                spec = importlib.util.spec_from_file_location(stem, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                results.append((version, stem, mod))
            return results

        with patch("sylvan.database.migrations.runner._discover_migrations", fake_discover):
            rolled_back = await rollback_migration(ctx.backend)

        assert rolled_back is not None
        assert "006_create_gadgets" in rolled_back
        assert await get_current_version(ctx.backend) == 5

        row = await ctx.backend.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name='gadgets'")
        assert row is None

    async def test_rollback_returns_none_at_version_zero(self, ctx):
        """Returns None when there's nothing to roll back.

        Returns:
            None.
        """
        # Clear migration history so version is 0
        await ctx.backend.execute("DELETE FROM _migrations")
        await ctx.backend.commit()
        result = await rollback_migration(ctx.backend)
        assert result is None


class TestCreateMigration:
    def test_creates_numbered_file(self, tmp_path):
        """Creates a migration file with correct numbering.

        Returns:
            None.
        """
        with (
            patch("sylvan.database.migrations.runner.MIGRATIONS_DIR", tmp_path),
            patch("sylvan.database.migrations.runner._discover_migrations", return_value=[]),
        ):
            filepath = create_migration("add users table")

        assert filepath.exists()
        assert filepath.name.startswith("001_")
        assert "add_users_table" in filepath.name
        content = filepath.read_text(encoding="utf-8")
        assert "async def up(" in content
        assert "async def down(" in content

    def test_increments_version(self, tmp_path):
        """New migration gets the next version number.

        Returns:
            None.
        """
        fake_migrations = [(5, "005_something", None)]
        with (
            patch("sylvan.database.migrations.runner.MIGRATIONS_DIR", tmp_path),
            patch("sylvan.database.migrations.runner._discover_migrations", return_value=fake_migrations),
        ):
            filepath = create_migration("next thing")

        assert filepath.name.startswith("006_")
