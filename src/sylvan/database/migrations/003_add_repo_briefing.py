"""Migration 003: Add briefing column to repos table."""

from sylvan.database.backends.base import Dialect, StorageBackend


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    """Add pre-computed briefing text to repos."""
    await backend.execute("ALTER TABLE repos ADD COLUMN briefing TEXT")
    await backend.commit()


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    """Remove briefing column."""
    await backend.execute("ALTER TABLE repos DROP COLUMN briefing")
    await backend.commit()
