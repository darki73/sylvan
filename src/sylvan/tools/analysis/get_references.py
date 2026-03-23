"""MCP tool: get_references -- who calls this symbol / what does it call."""

from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def get_references(symbol_id: str, direction: str = "to") -> dict:
    """Get references to or from a symbol.

    Args:
        symbol_id: The symbol to query.
        direction: ``"to"`` for callers (who references this symbol),
            ``"from"`` for callees (what this symbol references).

    Returns:
        Tool response dict with ``references`` list and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    from sylvan.analysis.structure.reference_graph import get_references_from, get_references_to

    if direction == "from":
        refs = await get_references_from(symbol_id)
    else:
        refs = await get_references_to(symbol_id)

    meta.set("count", len(refs))
    meta.set("direction", direction)
    return wrap_response({"references": refs, "symbol_id": symbol_id}, meta.build())
