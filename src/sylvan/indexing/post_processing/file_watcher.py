"""Optional file watcher for live re-indexing on file changes."""

import asyncio
from pathlib import Path

from sylvan.logging import get_logger

logger = get_logger(__name__)


async def watch_folder(
    folder_path: str,
    repo_name: str | None = None,
    debounce_ms: int = 2000,
) -> None:
    """Watch a folder for changes and trigger incremental re-indexing.

    Requires the 'watchfiles' optional dependency.

    Args:
        folder_path: Path to watch.
        repo_name: Repo name for re-indexing.
        debounce_ms: Milliseconds to wait after last change before re-indexing.
    """
    try:
        from watchfiles import Change, awatch
    except ImportError:
        logger.error("watchfiles not installed. Install with: pip install sylvan[watch]")
        return

    root = Path(folder_path).resolve()
    if repo_name is None:
        repo_name = root.name

    logger.info("watching_folder", path=str(root), debounce_ms=debounce_ms)

    async for changes in awatch(root, debounce=debounce_ms):
        changed_files = _collect_changed_files(changes, root)

        if changed_files:
            logger.info("reindexing_changed_files", count=len(changed_files), repo=repo_name)
            await _reindex(root, repo_name)


def _collect_changed_files(changes: object, root: Path) -> list[str]:
    """Filter and collect changed file paths from a set of watchfiles changes.

    Args:
        changes: Set of (change_type, path) tuples from watchfiles.
        root: Repository root directory.

    Returns:
        List of relative paths for files that were added or modified.
    """
    from watchfiles import Change

    from sylvan.security.patterns import should_skip_dir, should_skip_file

    changed_files = []
    for change_type, path_str in changes:
        path = Path(path_str)
        rel = str(path.relative_to(root)).replace("\\", "/")

        parts = Path(rel).parts
        if any(should_skip_dir(p) for p in parts[:-1]):
            continue
        if should_skip_file(path.name):
            continue
        if path.name.startswith("."):
            continue

        if change_type in (Change.added, Change.modified):
            changed_files.append(rel)
            logger.debug("file_changed", path=rel)

    return changed_files


async def _reindex(root: Path, repo_name: str) -> None:
    """Run a full re-index (incremental via hash check).

    Args:
        root: Repository root directory.
        repo_name: Display name of the repository.
    """
    try:
        from sylvan.indexing.pipeline.orchestrator import index_folder

        result = await index_folder(str(root), name=repo_name)
        logger.info(
            "reindex_complete",
            files=result.files_indexed,
            symbols=result.symbols_extracted,
        )
    except Exception as e:
        logger.error("reindex_failed", error=str(e))


def start_watcher_background(folder_path: str, repo_name: str | None = None) -> None:
    """Start the file watcher in a background thread.

    Args:
        folder_path: Path to watch for changes.
        repo_name: Optional repo name for re-indexing.
    """
    import threading

    def _run() -> None:
        """Run the async watcher in a new event loop."""
        asyncio.run(watch_folder(folder_path, repo_name))

    thread = threading.Thread(target=_run, daemon=True, name="sylvan-watcher")
    thread.start()
    logger.info("File watcher started in background thread")
