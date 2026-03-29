"""MCP tool: get_repo_outline -- high-level summary of an indexed repo."""

from sylvan.error_codes import SylvanError
from sylvan.services.symbol import SymbolService
from sylvan.tools.support.response import (
    check_staleness,
    ensure_orm,
    get_meta,
    log_tool_call,
    wrap_response,
)


@log_tool_call
async def get_repo_outline(repo: str) -> dict:
    """Get a high-level outline of an indexed repository.

    Shows file count, symbol count by kind, language distribution,
    and documentation overview.

    Args:
        repo: Repository name.

    Returns:
        Tool response dict with repo statistics and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    try:
        result = await SymbolService().repo_outline(repo)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    repo_id = result.pop("repo_id")

    meta.set("repo", repo)
    response = wrap_response(result, meta.build())
    await check_staleness(repo_id, response)
    return response
