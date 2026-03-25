"""MCP tool: find_importers -- find files that import a given file."""

from sylvan.database.orm import FileRecord, Symbol
from sylvan.database.orm.models.file_import import FileImport
from sylvan.error_codes import IndexFileNotFoundError
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response


async def _find_files_that_are_imported(importer_file_ids: list[int]) -> set[int]:
    """Determine which of the given file IDs are themselves import targets.

    This lets the caller know whether to recurse further up the import
    graph -- a file with no importers is a dead end.

    Args:
        importer_file_ids: List of file IDs to check.

    Returns:
        Set of file IDs from the input that are themselves imported
        by other files.
    """
    if not importer_file_ids:
        return set()

    rows = (
        await FileImport.query()
        .select("DISTINCT file_imports.resolved_file_id")
        .where_in(
            "file_imports.resolved_file_id",
            importer_file_ids,
        )
        .get()
    )
    return {row.resolved_file_id for row in rows}


@log_tool_call
async def find_importers(repo: str, file_path: str, max_results: int = 50) -> dict:
    """Find all files that import a given file.

    Args:
        repo: Repository name.
        file_path: The file to find importers of.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``importers`` list and ``_meta`` envelope.

    Raises:
        IndexFileNotFoundError: If the target file does not exist in the repo's index.
    """
    meta = MetaBuilder()
    max_results = clamp(max_results, 1, 1000)
    ensure_orm()

    target = await (
        FileRecord.query()
        .join("repos", "repos.id = files.repo_id")
        .where("repos.name", repo)
        .where("files.path", file_path)
        .first()
    )

    if target is None:
        raise IndexFileNotFoundError(file_path=file_path, _meta=meta.build())

    importing_files = await (
        FileRecord.query()
        .select("DISTINCT files.path", "files.language", "files.id")
        .join("file_imports fi", "fi.file_id = files.id")
        .where("fi.resolved_file_id", target.id)
        .order_by("files.path")
        .limit(max_results)
        .get()
    )

    importer_file_ids = [f.id for f in importing_files]
    files_that_are_imported = await _find_files_that_are_imported(importer_file_ids)

    importers = []
    for f in importing_files:
        symbol_count = await Symbol.where(file_id=f.id).count()
        importers.append(
            {
                "path": f.path,
                "language": f.language,
                "symbol_count": symbol_count,
                "has_importers": f.id in files_that_are_imported,
            }
        )

    meta.set("count", len(importers))
    return wrap_response({"file": file_path, "importers": importers}, meta.build())


@log_tool_call
async def batch_find_importers(repo: str, file_paths: list[str], max_results: int = 20) -> dict:
    """Find importers for multiple files in one call.

    Args:
        repo: Repository name.
        file_paths: List of file paths to find importers of.
        max_results: Maximum importers per file.

    Returns:
        Tool response dict with ``results`` list (one per file),
        ``not_found`` list, and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    max_results = clamp(max_results, 1, 100)
    ensure_orm()

    results = []
    not_found = []

    for fp in file_paths:
        target = await (
            FileRecord.query()
            .join("repos", "repos.id = files.repo_id")
            .where("repos.name", repo)
            .where("files.path", fp)
            .first()
        )

        if target is None:
            not_found.append(fp)
            continue

        importing_files = await (
            FileRecord.query()
            .select("DISTINCT files.path", "files.language", "files.id")
            .join("file_imports fi", "fi.file_id = files.id")
            .where("fi.resolved_file_id", target.id)
            .order_by("files.path")
            .limit(max_results)
            .get()
        )

        importers = [{"path": f.path, "language": f.language} for f in importing_files]

        results.append(
            {
                "file": fp,
                "importer_count": len(importers),
                "importers": importers,
            }
        )

    meta.set("found", len(results))
    meta.set("not_found", len(not_found))
    meta.set("total_importers", sum(r["importer_count"] for r in results))
    return wrap_response({"results": results, "not_found": not_found}, meta.build())
