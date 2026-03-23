"""MCP tool: remove_library -- remove an indexed library."""

from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


@log_tool_call
async def remove_library(name: str) -> dict:
    """Remove an indexed library and its source files.

    Args:
        name: Library name like ``"django@4.2"`` or ``"pip/django@4.2"``.

    Returns:
        Tool response dict with removal status and ``_meta`` envelope.
    """
    meta = MetaBuilder()

    from sylvan.libraries.manager import async_remove_library
    result = await async_remove_library(name)
    meta.set("status", result.get("status", ""))
    return wrap_response(result, meta.build())
