"""MCP tool: get_blast_radius -- estimate impact of changing a symbol."""

from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def get_blast_radius(symbol_id: str, depth: int = 2) -> dict:
    """Estimate the blast radius of changing a symbol.

    Shows which files and symbols would be affected by a change,
    with confirmed (name appears) vs potential (file imports only) impact.

    Args:
        symbol_id: The symbol to analyse.
        depth: How many import hops to follow (1--3).

    Returns:
        Tool response dict with ``confirmed`` and ``potential`` lists
        plus ``_meta`` envelope.
    """
    meta = MetaBuilder()
    depth = min(max(depth, 1), 3)
    ensure_orm()

    from sylvan.analysis.impact.blast_radius import get_blast_radius as _blast
    result = await _blast(symbol_id, max_depth=depth)
    meta.set("confirmed_count", len(result.get("confirmed", [])))
    meta.set("potential_count", len(result.get("potential", [])))
    return wrap_response(result, meta.build())


@log_tool_call
async def batch_blast_radius(symbol_ids: list[str], depth: int = 2) -> dict:
    """Estimate blast radius for multiple symbols in one call.

    Args:
        symbol_ids: List of symbol identifiers to analyse.
        depth: How many import hops to follow (1--3).

    Returns:
        Tool response dict with ``results`` list (one per symbol)
        and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    depth = min(max(depth, 1), 3)
    ensure_orm()

    from sylvan.analysis.impact.blast_radius import get_blast_radius as _blast

    results = []
    for sid in symbol_ids:
        try:
            result = await _blast(sid, max_depth=depth)
            results.append({
                "symbol_id": sid,
                "confirmed": result.get("confirmed", []),
                "potential": result.get("potential", []),
                "confirmed_count": len(result.get("confirmed", [])),
                "potential_count": len(result.get("potential", [])),
            })
        except Exception as exc:
            results.append({"symbol_id": sid, "error": str(exc)})

    meta.set("symbols_analysed", len(results))
    meta.set("total_confirmed", sum(r.get("confirmed_count", 0) for r in results))
    meta.set("total_potential", sum(r.get("potential_count", 0) for r in results))
    return wrap_response({"results": results}, meta.build())
