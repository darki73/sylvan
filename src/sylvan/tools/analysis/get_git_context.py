"""MCP tool: get_git_context -- git blame, change history, branch diffs."""

from sylvan.tools.support.response import ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def get_git_context(
    repo: str,
    file_path: str | None = None,
    symbol_id: str | None = None,
) -> dict:
    """Get git context for a file or symbol: blame, change frequency, recent commits.

    Args:
        repo: Repository name.
        file_path: File to get git context for.
        symbol_id: Symbol to get blame for (alternative to *file_path*).

    Returns:
        Tool response dict with blame/commit data and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.git import GitService

        result = await GitService().context(repo, file_path=file_path, symbol_id=symbol_id)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    return wrap_response(result, meta.build())
