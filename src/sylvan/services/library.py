"""Library service - add, list, remove, check, and compare third-party libraries."""

from __future__ import annotations

from pathlib import Path

from sylvan.database.orm import Repo, Symbol


async def add_library(package: str) -> dict:
    """Index a third-party library's source code for precise API lookup.

    Args:
        package: Package spec like "pip/django@4.2", "npm/react",
            or "go/github.com/gin-gonic/gin@v1.9.1".

    Returns:
        Dict with library status.

    Raises:
        ValueError: If the package spec is malformed.
    """
    from sylvan.libraries.manager import async_add_library

    return await async_add_library(package)


async def list_libraries() -> list[dict]:
    """List all indexed third-party libraries with their versions and stats.

    Returns:
        List of library dicts.
    """
    from sylvan.libraries.manager import async_list_libraries

    return await async_list_libraries()


async def remove_library(name: str) -> dict:
    """Remove an indexed library and its source files.

    Args:
        name: Library name like "django@4.2" or "pip/django@4.2".

    Returns:
        Dict with removal status.
    """
    from sylvan.libraries.manager import async_remove_library

    return await async_remove_library(name)


async def check_versions(repo: str) -> dict:
    """Compare a project's installed dependencies against indexed library versions.

    Reads the project's dependency files and cross-references each dependency
    against the sylvan library index.

    Args:
        repo: Indexed repository name to check dependencies for.

    Returns:
        Dict with outdated, up_to_date, and not_indexed lists.
    """
    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None or not repo_obj.source_path:
        return {"error": f"Repository '{repo}' not found or has no source path."}

    from sylvan.git.dependency_files import parse_dependencies

    installed_deps = parse_dependencies(Path(repo_obj.source_path))

    if not installed_deps:
        return {
            "message": "No dependency files found in project root.",
            "outdated": [],
            "up_to_date": [],
            "not_indexed": [],
        }

    indexed_libraries = await Repo.where(repo_type="library").get()

    indexed_by_package: dict[str, list[dict]] = {}
    for lib in indexed_libraries:
        if lib.package_manager and lib.package_name:
            key = f"{lib.package_manager}/{lib.package_name}"
            indexed_by_package.setdefault(key, []).append(
                {
                    "name": lib.name,
                    "version": lib.version,
                    "repo_id": lib.id,
                }
            )

    outdated: list[dict] = []
    up_to_date: list[dict] = []
    not_indexed: list[dict] = []

    for dep in installed_deps:
        manager = dep["manager"]
        name = dep["name"]
        installed_version = dep["version"] or "unknown"
        key = f"{manager}/{name}"

        if key not in indexed_by_package:
            not_indexed.append(
                {
                    "manager": manager,
                    "name": name,
                    "installed_version": installed_version,
                }
            )
            continue

        versions = indexed_by_package[key]
        indexed_versions = [v["version"] for v in versions]

        if installed_version in indexed_versions:
            up_to_date.append(
                {
                    "manager": manager,
                    "name": name,
                    "version": installed_version,
                }
            )
        else:
            outdated.append(
                {
                    "manager": manager,
                    "name": name,
                    "installed_version": installed_version,
                    "indexed_versions": indexed_versions,
                }
            )

    return {
        "outdated": outdated,
        "up_to_date": up_to_date,
        "not_indexed": not_indexed,
        "total_deps": len(installed_deps),
        "outdated_count": len(outdated),
        "up_to_date_count": len(up_to_date),
        "not_indexed_count": len(not_indexed),
    }


async def compare_versions(package: str, from_version: str, to_version: str) -> dict:
    """Compare two indexed versions of the same library.

    Generates a migration-relevant diff: symbols added, removed, and
    changed (signature differences).

    Args:
        package: Package name without manager prefix (e.g. "numpy").
        from_version: The old version string (e.g. "1.1.1").
        to_version: The new version string (e.g. "2.2.2").

    Returns:
        Dict with added, removed, and changed symbol lists.
    """
    old_name = f"{package}@{from_version}"
    new_name = f"{package}@{to_version}"

    old_repo = await Repo.where(name=old_name).where(repo_type="library").first()
    new_repo = await Repo.where(name=new_name).where(repo_type="library").first()

    if old_repo is None:
        return {"error": f"Library '{old_name}' is not indexed. Run add_library first."}
    if new_repo is None:
        return {"error": f"Library '{new_name}' is not indexed. Run add_library first."}

    old_symbols = await (
        Symbol.query()
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", old_repo.id)
        .where(kind="function")
        .or_where(kind="class")
        .or_where(kind="method")
        .get()
    )

    new_symbols = await (
        Symbol.query()
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", new_repo.id)
        .where(kind="function")
        .or_where(kind="class")
        .or_where(kind="method")
        .get()
    )

    old_by_name: dict[str, dict] = {}
    for symbol in old_symbols:
        old_by_name[symbol.qualified_name] = {
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "kind": symbol.kind,
            "signature": symbol.signature or "",
        }

    new_by_name: dict[str, dict] = {}
    for symbol in new_symbols:
        new_by_name[symbol.qualified_name] = {
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "kind": symbol.kind,
            "signature": symbol.signature or "",
        }

    old_names = set(old_by_name.keys())
    new_names = set(new_by_name.keys())

    added = [new_by_name[name] for name in sorted(new_names - old_names)]
    removed = [old_by_name[name] for name in sorted(old_names - new_names)]

    changed = []
    for name in sorted(old_names & new_names):
        old_sig = old_by_name[name]["signature"]
        new_sig = new_by_name[name]["signature"]
        if old_sig != new_sig:
            changed.append(
                {
                    "qualified_name": name,
                    "kind": old_by_name[name]["kind"],
                    "old_signature": old_sig,
                    "new_signature": new_sig,
                }
            )

    return {
        "package": package,
        "from_version": from_version,
        "to_version": to_version,
        "added": added[:50],
        "removed": removed[:50],
        "changed": changed[:50],
        "summary": {
            "total_added": len(added),
            "total_removed": len(removed),
            "total_changed": len(changed),
            "breaking_risk": "high" if removed or changed else "low",
        },
    }
