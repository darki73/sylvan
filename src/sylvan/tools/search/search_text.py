"""MCP tool: search_text -- full-text search across file content."""

from sylvan.services.search import SearchService
from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def search_text(
    query: str,
    repo: str | None = None,
    file_pattern: str | None = None,
    max_results: int = 20,
    context_lines: int = 2,
) -> dict:
    """Search across file content for text matches (like grep).

    Searches cached blob content without hitting the filesystem.

    Args:
        query: Text to search for (case-insensitive).
        repo: Repository name filter.
        file_pattern: Glob pattern to filter by file path.
        max_results: Maximum matches to return.
        context_lines: Number of surrounding lines per match.

    Returns:
        Tool response dict with ``matches`` list and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    data = await SearchService().text(
        query,
        repo=repo,
        file_pattern=file_pattern,
        max_results=max_results,
        context_lines=context_lines,
    )

    meta.set("results_count", data["results_count"])
    meta.set("query", data["query"])

    returned_tokens = data["returned_tokens"]
    equivalent_tokens = data["equivalent_tokens"]
    if returned_tokens > 0 and equivalent_tokens > 0:
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method="byte_estimate")

    repo_id = data["repo_id"]
    if repo_id:
        meta.set("repo_id", repo_id)

    return wrap_response({"matches": data["matches"]}, meta.build())
