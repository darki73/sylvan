"""MCP tool: get_blast_radius -- estimate impact of changing a symbol."""

from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def get_blast_radius(symbol_id: str, depth: int = 2) -> dict:
    """Estimate the blast radius of changing a symbol.

    Shows which files and symbols would be affected by a change,
    with confirmed (name appears) vs potential (file imports only) impact.

    Args:
        symbol_id: The symbol to analyse.
        depth: How many import hops to follow (1-3).

    Returns:
        Tool response dict with ``confirmed`` and ``potential`` lists
        plus ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.services.analysis import AnalysisService

    result = await AnalysisService().blast_radius(symbol_id, depth=depth)
    meta.set("confirmed_count", len(result.get("confirmed", [])))
    meta.set("potential_count", len(result.get("potential", [])))
    return wrap_response(result, meta.build())


@log_tool_call
async def batch_blast_radius(symbol_ids: list[str], depth: int = 2) -> dict:
    """Estimate blast radius for multiple symbols in one call.

    Args:
        symbol_ids: List of symbol identifiers to analyse.
        depth: How many import hops to follow (1-3).

    Returns:
        Tool response dict with ``results`` list (one per symbol)
        and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.services.analysis import AnalysisService

    data = await AnalysisService().batch_blast_radius(symbol_ids, depth=depth)
    meta.set("symbols_analysed", data["symbols_analysed"])
    meta.set("total_affected", data["total_affected"])
    return wrap_response({"results": data["results"]}, meta.build())
