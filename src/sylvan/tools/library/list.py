"""MCP tool: list_libraries -- show all indexed third-party libraries."""

from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


@log_tool_call
async def list_libraries() -> dict:
    """List all indexed third-party libraries with their versions and stats.

    Returns:
        Tool response dict with ``libraries`` list and ``_meta`` envelope.
    """
    meta = MetaBuilder()

    from sylvan.libraries.manager import async_list_libraries
    libs = await async_list_libraries()
    meta.set("count", len(libs))
    return wrap_response({"libraries": libs}, meta.build())
