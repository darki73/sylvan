"""Migration 005: Add complexity columns to symbols table."""

from sylvan.database.backends.base import Dialect, StorageBackend


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    """Add cyclomatic, max_nesting, and param_count to symbols."""
    await backend.execute("ALTER TABLE symbols ADD COLUMN cyclomatic INTEGER DEFAULT 0")
    await backend.execute("ALTER TABLE symbols ADD COLUMN max_nesting INTEGER DEFAULT 0")
    await backend.execute("ALTER TABLE symbols ADD COLUMN param_count INTEGER DEFAULT 0")
    await backend.commit()


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    """Remove complexity columns."""
    await backend.execute("ALTER TABLE symbols DROP COLUMN cyclomatic")
    await backend.execute("ALTER TABLE symbols DROP COLUMN max_nesting")
    await backend.execute("ALTER TABLE symbols DROP COLUMN param_count")
    await backend.commit()
