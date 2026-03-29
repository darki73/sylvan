"""MCP tool: get_related -- find related symbols by co-location and naming."""

from sylvan.tools.support.response import clamp, ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def get_related(symbol_id: str, max_results: int = 10) -> dict:
    """Find symbols related to a given symbol.

    Scoring signals:
    - Same file: weight 3.0
    - Shared imports: weight 1.5
    - Name token overlap: weight 0.5

    Args:
        symbol_id: The symbol to find relations for.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``related`` list and ``_meta`` envelope.
    """
    meta = get_meta()
    max_results = clamp(max_results, 1, 100)
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.analysis import AnalysisService

        result = await AnalysisService().related(symbol_id, max_results=max_results)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    meta.set("count", len(result["related"]))
    return wrap_response(result, meta.build())
