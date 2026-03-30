"""Indexing service - folder and single-file indexing operations."""

from __future__ import annotations

from pathlib import Path

from sylvan.config import get_config
from sylvan.database.orm import FileRecord, Repo
from sylvan.database.orm.runtime.connection_manager import get_backend
from sylvan.error_codes import IndexFileNotFoundError, RepoNotFoundError


def _queue_is_running() -> bool:
    """Check if the job queue runner is active."""
    from sylvan.queue import _runner

    return _runner is not None and _runner._running


def _invalidate_staleness_cache(repo_id: int) -> None:
    """Clear the staleness cache for a repo after indexing.

    Args:
        repo_id: The repo's primary key.
    """
    try:
        from sylvan.tools.support.response import _staleness_cache

        _staleness_cache.pop(repo_id, None)
    except ImportError:
        pass


async def index_folder(path: str, name: str | None = None, *, force: bool = False) -> dict:
    """Index a local folder for code symbol retrieval.

    Submits the work to the job queue when available (MCP server),
    falling back to direct execution otherwise (CLI).

    Args:
        path: Absolute path to the folder to index.
        name: Display name (defaults to folder name).
        force: If True, re-extract all files even if unchanged.

    Returns:
        Dict with indexing stats (repo name, files indexed, symbols extracted).
    """
    if _queue_is_running():
        from sylvan.queue import submit

        future = await submit("index_folder", key=f"index:{name or path}", path=path, name=name, force=force)
        return await future

    from sylvan.context import get_context
    from sylvan.indexing.pipeline.orchestrator import index_folder as _index_folder

    result = await _index_folder(path, name=name, force=force)

    _invalidate_staleness_cache(result.repo_id)
    get_context().cache.clear()

    if result.repo_id:
        from sylvan.indexing.post_processing.background_tasks import run_post_processing

        await run_post_processing(result.repo_id)

    return {
        **result.to_dict(),
        "repo": result.repo_name,
        "files_indexed": result.files_indexed,
        "symbols_extracted": result.symbols_extracted,
    }


async def index_file(repo: str, file_path: str) -> dict:
    """Reindex a single file without touching the rest of the repo.

    Submits the work to the job queue when available (MCP server),
    falling back to direct execution otherwise (CLI).

    Args:
        repo: Repository name (as shown in list_repos).
        file_path: Relative path within the repo (e.g., "src/main.py").

    Returns:
        Dict with indexing stats for the single file.

    Raises:
        RepoNotFoundError: If the repo is not indexed.
        IndexFileNotFoundError: If the file is not found.
    """
    if _queue_is_running():
        from sylvan.queue import submit

        future = await submit("index_file", key=f"file:{repo}:{file_path}", repo=repo, file_path=file_path)
        return await future

    return await _index_file_direct(repo, file_path)


async def _index_file_direct(repo: str, file_path: str) -> dict:
    """Reindex a single file using the two-phase pipeline."""
    import asyncio

    from sylvan.context import get_context
    from sylvan.indexing.pipeline.file_processor import _extract_file, _persist_result
    from sylvan.indexing.pipeline.orchestrator import IndexResult

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo)

    repo_id = repo_obj.id
    source_path = Path(repo_obj.source_path)
    abs_path = _validate_file_path(source_path, file_path)
    rel_path = file_path.replace("\\", "/")

    existing = await FileRecord.where(repo_id=repo_id, path=rel_path).first()
    existing_hash = existing.content_hash if existing else None

    # Phase 1: extract in thread (non-blocking)
    file_result = await asyncio.to_thread(
        _extract_file,
        abs_path,
        rel_path,
        abs_path.stat().st_size,
        abs_path.stat().st_mtime,
        get_config().max_file_size,
        repo,
        existing_hash,
    )

    if file_result.error:
        return {"error": file_result.error}
    if file_result.skipped:
        return {"file_path": rel_path, "status": "unchanged", "symbols_extracted": 0}

    # Phase 2: persist on event loop
    backend = get_backend()
    idx_result = IndexResult()
    async with backend.transaction():
        syms, imps, secs = await _persist_result(
            file_result,
            repo_id,
            repo,
            existing.id if existing else None,
            idx_result,
        )

    from sylvan.indexing.pipeline.import_resolver import resolve_imports

    await resolve_imports(repo_id)

    _invalidate_staleness_cache(repo_id)
    get_context().cache.clear()

    from sylvan.indexing.post_processing.background_tasks import run_post_processing

    await run_post_processing(repo_id)

    return {
        "file_path": rel_path,
        "symbols_extracted": syms,
        "imports_extracted": imps,
        "sections_extracted": secs,
        "status": "updated",
    }


def _validate_file_path(source_path: Path, file_path: str) -> Path:
    """Resolve and validate the absolute file path within the repo root.

    Args:
        source_path: The repository root directory.
        file_path: Relative path within the repo.

    Returns:
        The validated absolute file path.

    Raises:
        IndexFileNotFoundError: If the path escapes the repo root or doesn't exist.
    """
    abs_path = (source_path / file_path).resolve()

    try:
        abs_path.relative_to(source_path.resolve())
    except ValueError as exc:
        raise IndexFileNotFoundError(
            f"Path '{file_path}' resolves outside the repository root.",
            file_path=file_path,
        ) from exc

    if not abs_path.is_file():
        raise IndexFileNotFoundError(file_path=file_path)

    return abs_path
