"""MCP tool: calls_to - find all symbols that a given function calls."""

from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def calls_to(symbol_id: str, max_results: int = 50) -> dict:
    """Find all symbols that a given function or method calls.

    Args:
        symbol_id: The symbol to find callees of.
        max_results: Maximum number of results to return.

    Returns:
        Tool response dict with callees list and _meta envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.analysis.structure.reference_graph import get_references_from

    refs = await get_references_from(symbol_id)
    refs = refs[:max_results]
    meta.set("count", len(refs))
    return wrap_response(
        {"callees": refs, "symbol_id": symbol_id},
        meta.build(),
    )
