"""MCP tool: get_recent_changes -- file-level summary of recent git activity."""

from __future__ import annotations

from pathlib import Path

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def get_recent_changes(
    repo: str,
    commits: int = 5,
    file_path: str | None = None,
) -> dict:
    """Show what changed in the last N commits at the file level.

    For each changed file that is in the index, reports the file path,
    language, symbol count, and the most recent commit message touching
    that file.  A lighter alternative to ``get_symbol_diff`` when you
    just need an overview of recent activity.

    Args:
        repo: Repository name.
        commits: Number of commits to look back (default 5, max 100).
        file_path: Optional file path filter to restrict results.

    Returns:
        Tool response dict with changed files and summary.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = MetaBuilder()
    commits = clamp(commits, 1, 100)
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if not repo_obj:
        raise RepoNotFoundError(
            f"Repository '{repo}' is not indexed.",
            repo_name=repo,
            _meta=meta.build(),
        )

    source_root = Path(repo_obj.source_path) if repo_obj.source_path else None
    if source_root is None or not source_root.exists():
        return wrap_response(
            {"error": "source_unavailable", "detail": "Repository source path is not available on disk."},
            meta.build(),
        )

    from sylvan.git.diff import get_changed_files, get_commit_log

    changed = get_changed_files(source_root, f"HEAD~{commits}")

    if file_path:
        changed = [f for f in changed if f == file_path]

    files_changed: list[dict] = []

    for fp in changed:
        file_rec = await FileRecord.where(repo_id=repo_obj.id, path=fp).first()
        if file_rec is None:
            continue

        symbol_count = await Symbol.where(file_id=file_rec.id).count()

        log_entries = get_commit_log(source_root, file_path=fp, max_count=1)
        last_commit = log_entries[0] if log_entries else None

        entry: dict = {
            "file": fp,
            "language": file_rec.language,
            "symbol_count": symbol_count,
        }
        if last_commit:
            entry["last_commit"] = {
                "hash": last_commit["hash"][:8],
                "author": last_commit["author"],
                "date": last_commit["date"],
                "message": last_commit["message"],
            }

        files_changed.append(entry)

    meta.set("commits_back", commits)
    meta.set("files_changed", len(files_changed))

    return wrap_response(
        {
            "repo": repo,
            "commits": commits,
            "files_changed": files_changed,
            "summary": f"{len(files_changed)} indexed files changed across last {commits} commits",
        },
        meta.build(),
    )
