"""MCP tool: get_quality -- quality metrics for symbols."""

from sylvan.tools.support.response import ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def get_quality(
    repo: str,
    untested_only: bool = False,
    undocumented_only: bool = False,
    min_complexity: int = 0,
    limit: int = 50,
) -> dict:
    """Get quality metrics for symbols. Find untested, undocumented, or complex code.

    Lazily computes quality metrics on first access, then caches them.

    Args:
        repo: Repository name.
        untested_only: Only show untested symbols.
        undocumented_only: Only show undocumented symbols.
        min_complexity: Minimum cyclomatic complexity threshold.
        limit: Maximum results to return.

    Returns:
        Tool response dict with ``symbols`` quality list and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.analysis import AnalysisService

        result = await AnalysisService().quality(
            repo,
            untested_only=untested_only,
            undocumented_only=undocumented_only,
            min_complexity=min_complexity,
            limit=limit,
        )
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    meta.set("count", len(result["symbols"]))
    return wrap_response(result, meta.build())
