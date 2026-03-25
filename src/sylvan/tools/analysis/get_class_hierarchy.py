"""MCP tool: get_class_hierarchy -- traverse inheritance chains."""

from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


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
    meta = MetaBuilder()
    ensure_orm()

    from sylvan.analysis.structure.class_hierarchy import get_class_hierarchy as _hierarchy

    result = await _hierarchy(class_name, repo_name=repo)
    meta.set("ancestors", len(result.get("ancestors", [])))
    meta.set("descendants", len(result.get("descendants", [])))
    return wrap_response(result, meta.build())
