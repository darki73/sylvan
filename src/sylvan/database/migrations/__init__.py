"""Database migration system.

Migrations are numbered Python files in this directory. Each migration
has an ``async def up(backend)`` function (and optional ``async def down(backend)``
for rollback). The backend is a :class:`StorageBackend` instance.

Usage::

    from sylvan.database.migrations.runner import run_migrations
    await run_migrations(backend)
"""

from sylvan.database.migrations.runner import (
    create_migration,
    get_current_version,
    get_pending_migrations,
    rollback_migration,
    run_migrations,
)

__all__ = [
    "create_migration",
    "get_current_version",
    "get_pending_migrations",
    "rollback_migration",
    "run_migrations",
]
