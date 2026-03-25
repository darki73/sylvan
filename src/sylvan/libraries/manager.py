"""Library manager -- orchestrates add/remove/list/update.

Provides both sync (CLI, legacy -- wraps async) and async (MCP tool) entry points.
"""

import asyncio

from sylvan.libraries.resolution.package_registry import parse_package_spec, resolve
from sylvan.libraries.source_fetcher import fetch_source, get_library_path, remove_library_source
from sylvan.logging import get_logger

logger = get_logger(__name__)


def add_library(
    spec: str,
    timeout: int = 120,
) -> dict:
    """Add a library: resolve, fetch, index, and tag (sync wrapper).

    Args:
        spec: Package spec like ``"pip/django@4.2"`` or ``"npm/react"``.
        timeout: Fetch timeout in seconds.

    Returns:
        Dictionary with indexing results and library metadata.
    """
    return asyncio.run(_async_add_library_with_backend(spec, timeout=timeout))


async def _async_add_library_with_backend(
    spec: str,
    timeout: int = 120,
) -> dict:
    """Set up an async backend and delegate to async_add_library.

    Args:
        spec: Package spec.
        timeout: Fetch timeout in seconds.

    Returns:
        Dictionary with indexing results and library metadata.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, drain_pending_tasks, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        result = await async_add_library(spec, timeout=timeout)
        await drain_pending_tasks()

    await backend.disconnect()
    return result


async def async_add_library(
    spec: str,
    timeout: int = 120,
) -> dict:
    """Add a library: resolve, fetch, index, and tag (async).

    Assumes a SylvanContext with backend is already set.

    Args:
        spec: Package spec like ``"pip/django@4.2"`` or ``"npm/react"``.
        timeout: Fetch timeout in seconds.

    Returns:
        Dictionary with indexing results and library metadata.
    """
    from sylvan.database.orm import Repo
    from sylvan.database.orm.runtime.connection_manager import get_backend

    manager, name, version = parse_package_spec(spec)

    logger.info("resolving_package", manager=manager, name=name, version=version)
    info = resolve(manager, name, version)
    logger.info("package_resolved", name=info.name, version=info.version, repo_url=info.repo_url, tag=info.tag)

    display_name = f"{info.name}@{info.version}"
    existing = await Repo.where(name=display_name).where(repo_type="library").first()
    if existing:
        return {
            "status": "already_indexed",
            "name": display_name,
            "repo_id": existing.id,
            "message": f"Library {display_name} is already indexed.",
        }

    dest = get_library_path(manager, info.name, info.version)
    logger.info("fetching_source", dest=str(dest))
    fetch_source(info.repo_url, info.tag, dest, timeout=timeout)

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(dest), name=display_name)

    backend = get_backend()
    repo = await Repo.where(name=display_name).first()
    if repo:
        await repo.update(
            repo_type="library",
            package_manager=info.manager,
            package_name=info.name,
            version=info.version,
            github_url=info.repo_url,
        )
        await backend.commit()

    return {
        "status": "indexed",
        "name": display_name,
        "manager": info.manager,
        "package": info.name,
        "version": info.version,
        "repo_url": info.repo_url,
        "files_indexed": result.files_indexed,
        "symbols_extracted": result.symbols_extracted,
        "sections_extracted": result.sections_extracted,
        "duration_ms": result.duration_ms,
    }


def remove_library(spec: str) -> dict:
    """Remove a library's index and source files (sync wrapper).

    Args:
        spec: Library name like ``"django@4.2"`` or full spec
            ``"pip/django@4.2"``.

    Returns:
        Dictionary with removal status.
    """
    return asyncio.run(_async_remove_library_with_backend(spec))


async def _async_remove_library_with_backend(spec: str) -> dict:
    """Set up an async backend and delegate to async_remove_library.

    Args:
        spec: Library name or spec.

    Returns:
        Dictionary with removal status.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        result = await async_remove_library(spec)

    await backend.disconnect()
    return result


async def async_remove_library(spec: str) -> dict:
    """Remove a library's index and source files (async).

    Performs a full cascade delete of all associated data (references,
    quality, imports, sections, symbols, files) before removing the
    repo record itself, matching the pattern used by ``remove_repo``.

    Assumes a SylvanContext with backend is already set.

    Args:
        spec: Library name like ``"django@4.2"`` or full spec.

    Returns:
        Dictionary with removal status and per-table deletion counts.
    """
    from sylvan.database.orm import (
        FileImport,
        FileRecord,
        Quality,
        Reference,
        Repo,
        Section,
        Symbol,
    )
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()

    repo = await Repo.where(name=spec).where(repo_type="library").first()
    if repo is None:
        repo = await Repo.where_like("name", f"%{spec}%").where(repo_type="library").first()

    if repo is None:
        return {"status": "not_found", "message": f"Library '{spec}' not found."}

    if repo.package_manager and repo.package_name and repo.version:
        remove_library_source(repo.package_manager, repo.package_name, repo.version)

    repo_name = repo.name
    repo_id = repo.id

    files_q = FileRecord.where(repo_id=repo_id).to_subquery("id")
    symbols_q = Symbol.query().where_in_subquery("file_id", files_q).to_subquery("symbol_id")

    counts: dict[str, int] = {}

    async with backend.transaction():
        counts["references"] = await Reference.query().where_in_subquery("source_symbol_id", symbols_q).delete()
        counts["quality"] = await Quality.query().where_in_subquery("symbol_id", symbols_q).delete()
        counts["file_imports"] = await FileImport.query().where_in_subquery("file_id", files_q).delete()
        counts["sections"] = await Section.query().where_in_subquery("file_id", files_q).delete()
        counts["symbols"] = await Symbol.query().where_in_subquery("file_id", files_q).delete()
        counts["files"] = await FileRecord.where(repo_id=repo_id).delete()
        await repo.delete()
        counts["repos"] = 1

    return {"status": "removed", "name": repo_name, "deleted": counts}


def list_libraries() -> list[dict]:
    """List all indexed libraries (sync wrapper).

    Returns:
        List of dictionaries, one per indexed library.
    """
    return asyncio.run(_async_list_libraries_with_backend())


async def _async_list_libraries_with_backend() -> list[dict]:
    """Set up an async backend and delegate to async_list_libraries.

    Returns:
        List of dictionaries, one per indexed library.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        result = await async_list_libraries()

    await backend.disconnect()
    return result


async def async_list_libraries() -> list[dict]:
    """List all indexed libraries (async).

    Assumes a SylvanContext with backend is already set.

    Returns:
        List of dictionaries, one per indexed library.
    """
    from sylvan.database.orm import Repo
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()

    repos = await Repo.libraries().with_count("files").order_by("name").get()

    repo_ids = [r.id for r in repos]
    symbol_counts: dict[int, int] = {}
    if repo_ids:
        ph = ", ".join("?" for _ in repo_ids)
        rows = await backend.fetch_all(
            f"SELECT f.repo_id, COUNT(s.id) as cnt FROM symbols s "
            f"JOIN files f ON f.id = s.file_id "
            f"WHERE f.repo_id IN ({ph}) GROUP BY f.repo_id",
            repo_ids,
        )
        symbol_counts = {r["repo_id"]: r["cnt"] for r in rows}

    results = [
        {
            "name": r.name,
            "manager": r.package_manager,
            "package": r.package_name,
            "version": r.version,
            "repo_url": r.github_url,
            "files": getattr(r, "files_count", 0),
            "symbols": symbol_counts.get(r.id, 0),
            "indexed_at": r.indexed_at,
        }
        for r in repos
    ]

    return results


def update_library(spec: str, timeout: int = 120) -> dict:
    """Update a library to the latest version (sync wrapper).

    Removes the old version and fetches + indexes the latest.

    Args:
        spec: Library display name or partial match string.
        timeout: Fetch timeout in seconds.

    Returns:
        Dictionary with indexing results for the new version.
    """
    return asyncio.run(_async_update_library_with_backend(spec, timeout=timeout))


async def _async_update_library_with_backend(spec: str, timeout: int = 120) -> dict:
    """Set up an async backend and delegate to async_update_library.

    Args:
        spec: Library display name or partial match string.
        timeout: Fetch timeout in seconds.

    Returns:
        Dictionary with indexing results for the new version.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        result = await async_update_library(spec, timeout=timeout)

    await backend.disconnect()
    return result


async def async_update_library(spec: str, timeout: int = 120) -> dict:
    """Fetch and index the latest version of a library alongside the old one.

    Does NOT auto-transfer workspace pins or remove the old version.
    The agent should use ``compare_library_versions`` to assess breaking
    changes, then explicitly ``pin_library`` workspaces that are safe
    to upgrade.

    Assumes a SylvanContext with backend is already set.

    Args:
        spec: Library display name or partial match string.
        timeout: Fetch timeout in seconds.

    Returns:
        Dictionary with the new version info and a hint to compare.
    """
    from sylvan.database.orm import Repo

    old_repo = await Repo.where_like("name", f"%{spec}%").where(repo_type="library").first()
    if old_repo is None:
        return {"status": "not_found", "message": f"Library '{spec}' not found."}

    manager = old_repo.package_manager
    package = old_repo.package_name
    old_version = old_repo.version

    if not manager or not package:
        return {"status": "error", "message": "Library has no package manager info."}

    new_result = await async_add_library(f"{manager}/{package}", timeout=timeout)

    if new_result.get("status") == "already_indexed":
        return {
            "status": "already_latest",
            "name": old_repo.name,
            "message": f"{old_repo.name} is already the latest version.",
        }

    return {
        "status": "new_version_indexed",
        "old_version": old_version,
        "new_version": new_result.get("version", ""),
        "old_name": old_repo.name,
        "new_name": new_result.get("name", ""),
        "files_indexed": new_result.get("files_indexed", 0),
        "symbols_extracted": new_result.get("symbols_extracted", 0),
        "hint": ("Use compare_library_versions to see what changed, then pin_library to update specific workspaces."),
    }
