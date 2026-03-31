"""Migration 004: Add line column to references table."""

from sylvan.database.backends.base import Dialect, StorageBackend


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    """Add line number column to reference edges."""
    await backend.execute('ALTER TABLE "references" ADD COLUMN line INTEGER')
    await backend.commit()


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    """Remove line column."""
    await backend.execute('ALTER TABLE "references" DROP COLUMN line')
    await backend.commit()
