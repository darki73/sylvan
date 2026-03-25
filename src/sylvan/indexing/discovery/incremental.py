"""Git-aware incremental indexing -- only re-index changed files."""

from pathlib import Path

from sylvan.database.orm import FileRecord
from sylvan.git.diff import get_changed_files


async def get_files_to_reindex(
    repo_id: int,
    root: Path,
    last_git_head: str | None = None,
) -> list[str] | None:
    """Determine which files need re-indexing.

    Strategy:
    1. If git is available and we have a previous HEAD, use git diff
    2. Otherwise, compare file mtimes against stored values
    3. Returns None if no prior state (caller should do full index)

    Args:
        repo_id: Database ID of the repository.
        root: Repository root directory.
        last_git_head: Previous HEAD commit hash for git-based diffing.

    Returns:
        List of changed file paths, or None if no prior state exists
        and a full index is needed.
    """
    if last_git_head:
        changed = get_changed_files(root, since_commit=last_git_head)
        if changed:
            return changed

    stored_files = await FileRecord.where(repo_id=repo_id).select("path", "mtime").get()

    if not stored_files:
        return None

    changed = []
    for fr in stored_files:
        file_path = root / fr.path
        try:
            current_mtime = file_path.stat().st_mtime
            if fr.mtime is None or current_mtime > fr.mtime:
                changed.append(fr.path)
        except OSError:
            changed.append(fr.path)

    return changed
