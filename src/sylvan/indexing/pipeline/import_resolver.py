"""Post-indexing import specifier-to-file resolution.

Converts import specifiers (e.g. ``sylvan.search.embeddings``, ``./utils``)
into candidate file paths and matches them against the repo's indexed files
to populate ``resolved_file_id`` in the ``file_imports`` table.
"""

from __future__ import annotations

from sylvan.indexing.languages.protocols import ResolverContext
from sylvan.logging import get_logger

logger = get_logger(__name__)

_psr4_mappings: dict[int, dict[str, list[str]]] = {}
_tsconfig_aliases: dict[int, dict[str, list[str]]] = {}


def set_psr4_mappings(repo_id: int, mappings: dict[str, list[str]]) -> None:
    """Register PSR-4 autoload mappings for a repo.

    Args:
        repo_id: Repository database ID.
        mappings: Namespace prefix to directory list mapping from composer.json.
    """
    if mappings:
        _psr4_mappings[repo_id] = mappings
    else:
        _psr4_mappings.pop(repo_id, None)


def set_tsconfig_aliases(repo_id: int, aliases: dict[str, list[str]]) -> None:
    """Register tsconfig path aliases for a repo.

    Args:
        repo_id: Repository database ID.
        aliases: Alias pattern to resolved path list mapping from tsconfig.json.
            Patterns have their trailing ``/*`` stripped - e.g. ``@`` maps to
            ``["resources/js"]``.
    """
    if aliases:
        _tsconfig_aliases[repo_id] = aliases
    else:
        _tsconfig_aliases.pop(repo_id, None)


async def resolve_imports(repo_id: int) -> int:
    """Resolve file_imports specifiers to file IDs within a repo.

    Loads all indexed file paths for the repo, then for each unresolved
    import generates language-aware candidate paths and looks them up.
    Stale resolutions pointing to deleted/moved files are invalidated first.

    Args:
        repo_id: Repository to resolve imports for.

    Returns:
        Number of imports resolved.
    """
    from sylvan.config import get_config
    from sylvan.database.orm import FileRecord
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()

    # Invalidate resolutions pointing to deleted/moved files.
    await backend.execute(
        """UPDATE file_imports SET resolved_file_id = NULL
           WHERE resolved_file_id IS NOT NULL
           AND resolved_file_id NOT IN (SELECT id FROM files WHERE repo_id = ?)""",
        [repo_id],
    )

    # Build path -> file_id lookup for this repo.
    source_roots = get_config().indexing.source_roots
    files = await FileRecord.where(repo_id=repo_id).select("id", "path").get()
    path_to_id: dict[str, int] = {}
    for f in files:
        path_to_id[f.path] = f.id
        for prefix in source_roots:
            if prefix and f.path.startswith(prefix):
                path_to_id[f.path[len(prefix) :]] = f.id

    # Get all unresolved imports with their source file info.
    rows = await backend.fetch_all(
        """SELECT fi.id, fi.specifier, fi.file_id, f.path, f.language
           FROM file_imports fi
           JOIN files f ON f.id = fi.file_id
           WHERE fi.resolved_file_id IS NULL
           AND f.repo_id = ?""",
        [repo_id],
    )

    context = ResolverContext(
        psr4_mappings=_psr4_mappings.get(repo_id, {}),
        tsconfig_aliases=_tsconfig_aliases.get(repo_id, {}),
    )

    resolved_count = 0
    updates: list[tuple[int, int]] = []

    for row in rows:
        candidates = _generate_candidates(row["specifier"], row["language"], row["path"], context)

        for candidate in candidates:
            file_id = path_to_id.get(candidate)
            if file_id is not None:
                updates.append((file_id, row["id"]))
                resolved_count += 1
                break

    if updates:
        from sylvan.database.orm import FileImport

        await FileImport.bulk_update(
            [{"id": import_id, "resolved_file_id": file_id} for file_id, import_id in updates],
        )

    logger.info(
        "imports_resolved",
        repo_id=repo_id,
        total=len(rows),
        resolved=resolved_count,
    )
    return resolved_count


def _generate_candidates(
    specifier: str,
    language: str,
    source_path: str,
    context: ResolverContext,
) -> list[str]:
    """Generate candidate file paths from an import specifier.

    Delegates to the language plugin's import resolver if one is registered.

    Args:
        specifier: The raw import specifier string.
        language: Programming language of the importing file.
        source_path: Relative path of the file containing the import.
        context: Repo-scoped resolution state.

    Returns:
        Ordered list of candidate file paths to try matching.
    """
    from sylvan.indexing.languages import get_import_resolver

    resolver = get_import_resolver(language)
    if resolver is None:
        return []

    return resolver.generate_candidates(specifier, source_path, context)


async def resolve_cross_repo_imports(repo_ids: list[int]) -> int:
    """Resolve imports across multiple repos in a workspace.

    Loads file paths from ALL repos in the list, then resolves any remaining
    NULL resolved_file_id imports by looking across repos. Uses the same
    language-aware candidate generation as single-repo resolution.

    This should only be called from workspace tools, not from regular indexing.

    Args:
        repo_ids: List of repository database IDs to resolve across.

    Returns:
        Number of cross-repo imports resolved.
    """
    from sylvan.config import get_config
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()
    source_roots = get_config().indexing.source_roots

    # Build path -> file_id lookup across ALL repos.
    placeholder_list = ",".join("?" * len(repo_ids))
    all_files = await backend.fetch_all(
        f"SELECT id, path FROM files WHERE repo_id IN ({placeholder_list})",
        repo_ids,
    )
    path_to_id: dict[str, int] = {}
    for row in all_files:
        path_to_id[row["path"]] = row["id"]
        for prefix in source_roots:
            if prefix and row["path"].startswith(prefix):
                path_to_id[row["path"][len(prefix) :]] = row["id"]

    # Get all unresolved imports across these repos.
    rows = await backend.fetch_all(
        f"""SELECT fi.id, fi.specifier, fi.file_id, f.path, f.language
           FROM file_imports fi
           JOIN files f ON f.id = fi.file_id
           WHERE fi.resolved_file_id IS NULL
           AND f.repo_id IN ({placeholder_list})""",
        repo_ids,
    )

    # Cross-repo resolution uses empty context (no per-repo PSR-4/tsconfig).
    context = ResolverContext()

    resolved_count = 0
    updates: list[tuple[int, int]] = []

    for row in rows:
        candidates = _generate_candidates(row["specifier"], row["language"], row["path"], context)
        for candidate in candidates:
            file_id = path_to_id.get(candidate)
            if file_id is not None:
                updates.append((file_id, row["id"]))
                resolved_count += 1
                break

    if updates:
        async with backend.transaction():
            for file_id, import_id in updates:
                await backend.execute(
                    "UPDATE file_imports SET resolved_file_id = ? WHERE id = ?",
                    [file_id, import_id],
                )

    logger.info(
        "cross_repo_imports_resolved",
        repo_ids=repo_ids,
        total=len(rows),
        resolved=resolved_count,
    )
    return resolved_count
