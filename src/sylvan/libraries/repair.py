"""Library repair - detect corrupted library data and enqueue re-index jobs.

Scans the library directory on disk, compares against the database,
and repairs libraries that have missing or stale index data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from sylvan.logging import get_logger

logger = get_logger(__name__)


def scan_library_disk(library_root: Path) -> list[dict]:
    """Walk the library directory and return all installed versions.

    Expects ``library_root/manager/package/version/`` structure.

    Args:
        library_root: Root directory for library sources.

    Returns:
        List of dicts with manager, package, version, path, display_name.
    """
    results: list[dict] = []

    if not library_root.exists():
        return results

    for manager_dir in sorted(library_root.iterdir()):
        if not manager_dir.is_dir():
            continue
        manager = manager_dir.name
        for package_dir in sorted(manager_dir.iterdir()):
            if not package_dir.is_dir():
                continue
            package = package_dir.name
            for version_dir in sorted(package_dir.iterdir()):
                if not version_dir.is_dir():
                    continue
                version = version_dir.name
                # Convert folder name back to scoped package name.
                # e.g. @nuxt--eslint -> @nuxt/eslint
                display_package = package.replace("--", "/")
                results.append(
                    {
                        "manager": manager,
                        "package": display_package,
                        "version": version,
                        "path": str(version_dir),
                        "display_name": f"{display_package}@{version}",
                    }
                )

    return results


async def check_library_health(disk_libraries: list[dict]) -> list[dict]:
    """Check each on-disk library against the database.

    A library needs re-indexing if:
    - No repo record exists
    - Repo exists but has no files
    - Files exist but first file has no symbols
    - Symbols are not prefixed with ``display_name::`` (stale format)

    Args:
        disk_libraries: Output of ``scan_library_disk``.

    Returns:
        Subset of disk_libraries that need re-indexing, with a ``reason`` key.
    """
    from sylvan.database.orm import FileRecord, Repo, Symbol

    needs_reindex: list[dict] = []

    for lib in disk_libraries:
        display_name = lib["display_name"]

        repo = await Repo.where(name=display_name).where(repo_type="library").first()
        if not repo:
            logger.info("library_missing_repo", library=display_name)
            needs_reindex.append({**lib, "reason": "no_repo"})
            continue

        files = await FileRecord.where(repo_id=repo.id).get()
        if not files:
            logger.info("library_no_files", library=display_name)
            needs_reindex.append({**lib, "reason": "no_files"})
            continue

        file_ids = [f.id for f in files]
        total_symbols = await Symbol.query().where_in("file_id", file_ids).count()
        if total_symbols == 0:
            logger.info("library_no_symbols", library=display_name)
            needs_reindex.append({**lib, "reason": "no_symbols"})
            continue

        sample_symbols = await Symbol.query().where_in("file_id", file_ids).limit(5).get()
        prefix = f"{display_name}::"
        if not all(s.symbol_id.startswith(prefix) for s in sample_symbols):
            logger.info("library_stale_prefix", library=display_name)
            needs_reindex.append({**lib, "reason": "stale_prefix"})
            continue

    return needs_reindex


async def nuke_library_data(display_name: str) -> None:
    """Delete all DB data for a library without removing source files.

    Cleans up vec virtual tables first (no CASCADE support), then
    lets the ORM cascade handle the rest via ``repo.delete()``.

    Args:
        display_name: Library display name (e.g. ``"django@4.2"``).
    """
    from sylvan.database.orm import Repo
    from sylvan.services.repository import _cleanup_vec_tables

    repo = await Repo.where(name=display_name).where(repo_type="library").first()
    if repo is None:
        logger.debug("nuke_skipped_no_repo", library=display_name)
        return

    await _cleanup_vec_tables(repo.id)
    await repo.delete()
    logger.info("library_data_nuked", library=display_name, repo_id=repo.id)


async def repair_libraries() -> dict:
    """Scan for corrupted libraries and enqueue re-index jobs.

    Intended to be called during server startup. For each library
    that needs repair: nukes stale DB data, then submits an
    ``index_folder`` job to the queue.

    Returns:
        Dict with total scanned, list of repaired libraries,
        and list of any errors.
    """
    from sylvan.config import get_config
    from sylvan.queue import submit

    cfg = get_config()
    disk_libraries = scan_library_disk(cfg.library_path)

    if not disk_libraries:
        logger.debug("repair_no_libraries_on_disk")
        return {"scanned": 0, "repaired": [], "errors": []}

    stale = await check_library_health(disk_libraries)

    if not stale:
        logger.info("repair_all_healthy", total=len(disk_libraries))
        return {"scanned": len(disk_libraries), "repaired": [], "errors": []}

    logger.info("repair_found_stale", total=len(stale), scanned=len(disk_libraries))

    repaired: list[dict] = []
    errors: list[dict] = []

    for lib in stale:
        display_name = lib["display_name"]
        try:
            await nuke_library_data(display_name)
            repaired.append(
                {
                    "name": display_name,
                    "reason": lib["reason"],
                    "path": lib["path"],
                }
            )
        except Exception as exc:
            logger.warning("repair_nuke_failed", library=display_name, error=str(exc))
            errors.append({"name": display_name, "error": str(exc)})

    for lib_info in repaired:
        display_name = lib_info["name"]
        lib = next(entry for entry in stale if entry["display_name"] == display_name)
        try:
            await submit(
                "repair_library",
                key=f"repair:{display_name}",
                path=lib["path"],
                name=display_name,
                manager=lib["manager"],
                package=lib["package"],
                version=lib["version"],
            )
            logger.info("repair_enqueued", library=display_name, reason=lib_info["reason"])
        except Exception as exc:
            logger.warning("repair_enqueue_failed", library=display_name, error=str(exc))
            errors.append({"name": display_name, "error": str(exc)})

    return {
        "scanned": len(disk_libraries),
        "repaired": repaired,
        "errors": errors,
    }
