"""MCP tool: get_file_tree -- compact directory tree for a repo."""

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
async def get_file_tree(repo: str, max_depth: int = 3) -> dict:
    """Get a compact directory tree for an indexed repository.

    Returns an indented text tree (like the ``tree`` command) instead of
    deeply nested JSON -- much more token-efficient for LLM consumption.
    Directories beyond *max_depth* are collapsed with file counts.

    Args:
        repo: Repository name.
        max_depth: Maximum directory depth to expand (1--10).

    Returns:
        Tool response dict with ``tree`` string and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    try:
        data = await SymbolService().file_tree(repo, max_depth=max_depth)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    repo_id = data.pop("repo_id")
    truncated = data.pop("truncated")

    meta.set("repo", repo)
    meta.set("files", data.pop("files"))
    meta.set("max_depth", data.pop("max_depth"))
    if truncated:
        meta.set("truncated", True)

    response = wrap_response(data, meta.build())
    await check_staleness(repo_id, response)
    return response
