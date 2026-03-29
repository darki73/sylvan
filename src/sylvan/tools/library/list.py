"""MCP tool: list_libraries -- show all indexed third-party libraries."""

from sylvan.tools.support.response import get_meta, log_tool_call, wrap_response


@log_tool_call
async def list_libraries() -> dict:
    """List all indexed third-party libraries with their versions and stats.

    Returns:
        Tool response dict with ``libraries`` list and ``_meta`` envelope.
    """
    meta = get_meta()

    from sylvan.services.library import list_libraries as _svc

    libs = await _svc()
    meta.set("count", len(libs))
    return wrap_response({"libraries": libs}, meta.build())
