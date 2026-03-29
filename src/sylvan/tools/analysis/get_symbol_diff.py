"""MCP tool: get_symbol_diff -- compare symbols between git commits."""

from sylvan.tools.support.response import clamp, ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def get_symbol_diff(
    repo: str,
    commit: str = "HEAD~1",
    file_path: str | None = None,
    max_files: int = 50,
) -> dict:
    """Compare current symbols against a previous git commit.

    Extracts symbols from old file versions via ``git show`` and tree-sitter,
    then diffs against the current index to find added, removed, and changed
    symbols.

    Args:
        repo: Repository name.
        commit: Git ref to compare against (default ``HEAD~1``).
        file_path: Optional file path filter.
        max_files: Maximum number of files to diff.

    Returns:
        Tool response dict with per-file diffs and summary counts.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = get_meta()
    max_files = clamp(max_files, 1, 200)
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.git import GitService

        result = await GitService().symbol_diff(repo, commit=commit, file_path=file_path, max_files=max_files)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    if "error" in result:
        return wrap_response(result, meta.build())

    meta.set("files_compared", result.pop("files_compared"))
    meta.set("files_with_changes", result.pop("files_with_changes"))
    meta.set("commit", commit)

    return wrap_response(result, meta.build())
