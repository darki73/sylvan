"""File watcher driving live re-indexing on filesystem changes.

Backed by ``sylvan-indexing``'s Rust watcher (the ``notify`` crate)
since v2.x. The previous ``watchfiles`` optional dependency is gone;
watching is always available.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sylvan._rust import Watcher as _RustWatcher
from sylvan.logging import get_logger
from sylvan.security.patterns import should_skip_dir, should_skip_file

logger = get_logger(__name__)

_DEFAULT_DEBOUNCE_MS = 2000
_POLL_TIMEOUT_MS = 1000


async def watch_folder(
    folder_path: str,
    repo_name: str | None = None,
    debounce_ms: int = _DEFAULT_DEBOUNCE_MS,
) -> None:
    """Watch *folder_path* recursively and reindex when files change.

    Args:
        folder_path: Directory to watch.
        repo_name: Repo name to pass to the indexer. Defaults to the
            directory's basename.
        debounce_ms: Debounce window in milliseconds. Change flurries
            inside the window collapse into one reindex.
    """
    root = Path(folder_path).resolve()
    if repo_name is None:
        repo_name = root.name

    watcher = _RustWatcher(str(root), debounce_ms)
    logger.info("watching_folder", path=str(root), debounce_ms=debounce_ms)

    try:
        while True:
            batch = await asyncio.to_thread(watcher.next_batch, _POLL_TIMEOUT_MS)
            if not batch:
                continue
            changed = _filter_indexable(batch, root)
            if not changed:
                continue
            logger.info("reindexing_changed_files", count=len(changed), repo=repo_name)
            await _reindex(root, repo_name)
    finally:
        watcher.close()


def _filter_indexable(batch: list[tuple[str, str]], root: Path) -> list[str]:
    """Filter out events for paths the indexer would reject anyway.

    Args:
        batch: List of ``(kind, absolute_path)`` pairs emitted by the
            Rust watcher.
        root: Repository root directory.

    Returns:
        Relative paths whose changes warrant a reindex.
    """
    keep: list[str] = []
    for kind, raw_path in batch:
        if kind == "removed":
            # Removed files still need reindex to prune their symbols,
            # so we keep them too. Directory prune events land here as
            # "removed" with the directory path; the indexer handles
            # either case.
            pass
        elif kind not in {"added", "modified"}:
            continue

        path = Path(raw_path)
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue

        parts = Path(rel).parts
        if any(should_skip_dir(p) for p in parts[:-1]):
            continue
        name = parts[-1] if parts else path.name
        if should_skip_file(name) or name.startswith("."):
            continue
        keep.append(rel)
        logger.debug("file_changed", path=rel, kind=kind)
    return keep


async def _reindex(root: Path, repo_name: str) -> None:
    """Trigger an incremental reindex of *root*.

    Args:
        root: Repository root directory.
        repo_name: Repository display name.
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
    """Start :func:`watch_folder` in a daemon thread.

    Args:
        folder_path: Directory to watch.
        repo_name: Optional repo name forwarded to :func:`watch_folder`.
    """
    import threading

    def _run() -> None:
        asyncio.run(watch_folder(folder_path, repo_name))

    thread = threading.Thread(target=_run, daemon=True, name="sylvan-watcher")
    thread.start()
    logger.info("File watcher started in background thread")
