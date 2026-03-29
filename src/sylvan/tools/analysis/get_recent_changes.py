"""MCP tool: get_recent_changes -- file-level summary of recent git activity."""

from sylvan.tools.support.response import clamp, ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


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
    meta = get_meta()
    commits = clamp(commits, 1, 100)
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.git import GitService

        result = await GitService().recent_changes(repo, commits=commits, file_path=file_path)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    if "error" in result:
        return wrap_response(result, meta.build())

    meta.set("commits_back", result["commits"])
    meta.set("files_changed", len(result["files_changed"]))

    return wrap_response(result, meta.build())
