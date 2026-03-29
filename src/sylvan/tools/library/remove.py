"""MCP tool: remove_library -- remove an indexed library."""

from sylvan.tools.support.response import get_meta, log_tool_call, wrap_response


@log_tool_call
async def remove_library(name: str) -> dict:
    """Remove an indexed library and its source files.

    Args:
        name: Library name like ``"django@4.2"`` or ``"pip/django@4.2"``.

    Returns:
        Tool response dict with removal status and ``_meta`` envelope.
    """
    meta = get_meta()

    from sylvan.services.library import remove_library as _svc

    result = await _svc(name)
    meta.set("status", result.get("status", ""))
    return wrap_response(result, meta.build())
