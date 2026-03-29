"""MCP tool: suggest_queries -- intelligent query suggestions for exploring a repo."""

from sylvan.tools.support.response import ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def suggest_queries(repo: str) -> dict:
    """Suggest useful queries for exploring an indexed repository.

    Based on:
    - Repository structure (top symbols, entry points, key files)
    - Session context (what the agent has already explored)
    - Common exploration patterns

    Args:
        repo: Repository name.

    Returns:
        Tool response dict with ``suggestions`` list and ``_meta`` envelope.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.meta import suggest_queries as _svc

        result = await _svc(repo)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    meta.set("suggestion_count", len(result["suggestions"]))
    return wrap_response(result, meta.build())
