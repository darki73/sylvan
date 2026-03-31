"""MCP tool: get_repo_briefing -- structured repo orientation."""

from sylvan.error_codes import SylvanError
from sylvan.services.briefing import BriefingService
from sylvan.tools.support.response import (
    check_staleness,
    ensure_orm,
    get_meta,
    log_tool_call,
    wrap_response,
)


@log_tool_call
async def get_repo_briefing(repo: str) -> dict:
    """Get a structured orientation briefing for a repository.

    Returns stats, directory structure, language breakdown, and manifest
    contents for quick codebase orientation.

    Args:
        repo: Repository name.

    Returns:
        Tool response dict with briefing data and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    try:
        result = await BriefingService().get(repo)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    repo_id = result.pop("repo_id")

    meta.set("repo", repo)
    response = wrap_response(result, meta.build())
    await check_staleness(repo_id, response)
    return response
