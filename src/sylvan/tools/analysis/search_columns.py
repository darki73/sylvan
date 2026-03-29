"""MCP tool: search_columns -- search ecosystem context column metadata."""

from sylvan.tools.support.response import clamp, ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def search_columns(
    repo: str,
    query: str,
    model_pattern: str | None = None,
    max_results: int = 20,
) -> dict:
    """Search column metadata from ecosystem context providers.

    Discovers providers (e.g. dbt) for the repository's source path and
    searches their structured column metadata.

    Args:
        repo: Repository name.
        query: Search query for column names or descriptions.
        model_pattern: Optional glob pattern to filter model names.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``columns`` list and ``_meta`` envelope.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = get_meta()
    max_results = clamp(max_results, 1, 200)
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.analysis import AnalysisService

        result = await AnalysisService().search_columns(
            repo, query, model_pattern=model_pattern, max_results=max_results
        )
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    if "count" in result:
        meta.set("count", result.pop("count"))
    if "providers_found" in result:
        meta.set("providers_found", result.pop("providers_found"))
    if "providers" in result:
        meta.set("providers", result.pop("providers"))

    return wrap_response(result, meta.build())
