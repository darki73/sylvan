"""MCP tool: get_references -- who calls this symbol / what does it call."""

from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


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
    meta = get_meta()
    ensure_orm()

    from sylvan.services.analysis import AnalysisService

    result = await AnalysisService().references(symbol_id, direction=direction)
    meta.set("count", len(result["references"]))
    meta.set("direction", result["direction"])
    return wrap_response(
        {"references": result["references"], "symbol_id": result["symbol_id"]},
        meta.build(),
    )
