"""MCP tool: get_class_hierarchy -- traverse inheritance chains."""

from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def get_class_hierarchy(class_name: str, repo: str | None = None) -> dict:
    """Traverse class hierarchy: ancestors and descendants.

    Args:
        class_name: Name of the class to analyse.
        repo: Optional repository name filter.

    Returns:
        Tool response dict with ``ancestors`` and ``descendants`` lists
        plus ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.services.analysis import AnalysisService

    result = await AnalysisService().class_hierarchy(class_name, repo=repo)
    meta.set("ancestors", len(result.get("ancestors", [])))
    meta.set("descendants", len(result.get("descendants", [])))
    return wrap_response(result, meta.build())
