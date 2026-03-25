"""Migration runner — discovers and applies async migration files."""

import importlib
from datetime import UTC, datetime
from pathlib import Path

from sylvan.database.backends.base import StorageBackend
from sylvan.logging import get_logger

logger = get_logger(__name__)

MIGRATIONS_PACKAGE = "sylvan.database.migrations"
MIGRATIONS_DIR = Path(__file__).parent


async def _ensure_migration_table(backend: StorageBackend) -> None:
    """Create the migration tracking table if it doesn't exist.

    Args:
        backend: The async storage backend.
    """
    await backend.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    await backend.commit()


async def get_current_version(backend: StorageBackend) -> int:
    """Get the highest applied migration version.

    Args:
        backend: The async storage backend.

    Returns:
        The highest migration version number, or 0 if none applied.
    """
    await _ensure_migration_table(backend)
    result = await backend.fetch_value("SELECT MAX(version) FROM _migrations")
    return result if result is not None else 0


def _discover_migrations() -> list[tuple[int, str, object]]:
    """Discover all migration modules in the migrations package.

    Migration files must be named: NNN_description.py (e.g., 001_initial_schema.py).

    Returns:
        Sorted list of (version, name, module) tuples.
    """
    migrations = []

    for item in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.py")):
        stem = item.stem
        version_str = stem.split("_", 1)[0]
        try:
            version = int(version_str)
        except ValueError:
            continue

        module_name = f"{MIGRATIONS_PACKAGE}.{stem}"
        try:
            module = importlib.import_module(module_name)
            migrations.append((version, stem, module))
        except (ImportError, SyntaxError, AttributeError) as e:
            logger.warning("migration_import_failed", name=stem, error=str(e))

    return sorted(migrations, key=lambda x: x[0])


async def get_pending_migrations(backend: StorageBackend) -> list[tuple[int, str, object]]:
    """Get migrations that haven't been applied yet.

    Args:
        backend: The async storage backend.

    Returns:
        List of (version, name, module) tuples for pending migrations.
    """
    current = await get_current_version(backend)
    all_migrations = _discover_migrations()
    return [(v, name, mod) for v, name, mod in all_migrations if v > current]


async def run_migrations(backend: StorageBackend) -> list[str]:
    """Apply all pending migrations in order.

    Each migration module must define an ``async def up(backend, dialect)``
    function that receives the storage backend and its dialect, then
    performs schema changes.

    Args:
        backend: The async storage backend.

    Returns:
        List of applied migration names.

    Raises:
        RuntimeError: If a migration fails to apply.
    """
    await _ensure_migration_table(backend)
    pending = await get_pending_migrations(backend)

    if not pending:
        return []

    # Detect schema-ahead-of-code: DB was migrated by a newer version of Sylvan
    all_migrations = _discover_migrations()
    max_available_version = max((v for v, _, _ in all_migrations), default=0)
    current_version = await get_current_version(backend)
    if current_version > max_available_version:
        logger.warning(
            "schema_ahead_of_code",
            db_version=current_version,
            code_version=max_available_version,
        )

    applied = []
    for version, name, module in pending:
        up_fn = getattr(module, "up", None)
        if up_fn is None:
            logger.warning("migration_no_up_fn", name=name)
            continue

        logger.info("applying_migration", version=version, name=name)
        try:
            await up_fn(backend, backend.dialect)
            await backend.execute(
                "INSERT INTO _migrations (version, name, applied_at) VALUES (?, ?, ?)",
                [version, name, datetime.now(UTC).isoformat()],
            )
            await backend.commit()
            applied.append(name)
            logger.info("applied_migration", version=version, name=name)
        except Exception as e:
            logger.error("migration_failed", version=version, error=str(e))
            raise RuntimeError(f"Migration {name} failed: {e}") from e

    return applied


async def rollback_migration(backend: StorageBackend) -> str | None:
    """Roll back the most recent migration.

    Args:
        backend: The async storage backend.

    Returns:
        The migration name that was rolled back, or None if nothing to roll back.

    Raises:
        RuntimeError: If the migration has no down() function or rollback fails.
    """
    await _ensure_migration_table(backend)
    current = await get_current_version(backend)
    if current == 0:
        return None

    all_migrations = _discover_migrations()
    target = None
    for version, name, module in all_migrations:
        if version == current:
            target = (version, name, module)
            break

    if target is None:
        logger.warning("migration_not_found", version=current)
        return None

    version, name, module = target
    down_fn = getattr(module, "down", None)
    if down_fn is None:
        raise RuntimeError(f"Migration {name} has no down() function — cannot rollback")

    logger.info("rolling_back_migration", version=version, name=name)
    try:
        await down_fn(backend, backend.dialect)
        await backend.execute("DELETE FROM _migrations WHERE version = ?", [version])
        await backend.commit()
        logger.info("rolled_back_migration", version=version, name=name)
        return name
    except Exception as e:
        logger.error("rollback_failed", version=version, error=str(e))
        raise RuntimeError(f"Rollback of {name} failed: {e}") from e


def create_migration(description: str) -> Path:
    """Create a new empty migration file.

    Args:
        description: Human-readable description for the migration.

    Returns:
        Path to the created migration file.
    """
    all_migrations = _discover_migrations()
    next_version = max((v for v, _, _ in all_migrations), default=0) + 1

    safe_desc = description.lower().replace(" ", "_").replace("-", "_")
    safe_desc = "".join(c for c in safe_desc if c.isalnum() or c == "_")

    filename = f"{next_version:03d}_{safe_desc}.py"
    filepath = MIGRATIONS_DIR / filename

    filepath.write_text(
        f'''"""Migration {next_version:03d}: {description}."""

from sylvan.database.backends.base import Dialect, StorageBackend
from sylvan.database.builder import Schema


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    """Apply this migration.

    Args:
        backend: The async storage backend.
        dialect: The SQL dialect for database-specific SQL generation.
    """
    schema = Schema(backend)


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    """Reverse this migration.

    Args:
        backend: The async storage backend.
        dialect: The SQL dialect for database-specific SQL generation.
    """
    schema = Schema(backend)
''',
        encoding="utf-8",
    )

    return filepath
