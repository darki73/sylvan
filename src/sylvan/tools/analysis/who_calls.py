"""MCP tool: who_calls - find all symbols that call a given function."""

from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def who_calls(symbol_id: str, max_results: int = 50) -> dict:
    """Find all symbols that call a given function or method.

    Args:
        symbol_id: The symbol to find callers of.
        max_results: Maximum number of results to return.

    Returns:
        Tool response dict with callers list and _meta envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.analysis.structure.reference_graph import get_references_to

    refs = await get_references_to(symbol_id)
    refs = refs[:max_results]
    meta.set("count", len(refs))
    return wrap_response(
        {"callers": refs, "symbol_id": symbol_id},
        meta.build(),
    )
