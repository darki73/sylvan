"""MCP tool: search_sections -- search indexed documentation sections."""

from sylvan.error_codes import SylvanError
from sylvan.services.search import SearchService
from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def search_sections(
    query: str,
    repo: str | None = None,
    doc_path: str | None = None,
    max_results: int = 10,
) -> dict:
    """Search indexed documentation sections by title, summary, or tags.

    Args:
        query: Search query string.
        repo: Filter to a specific repository name.
        doc_path: Filter to a specific document path.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``sections`` list and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    try:
        data = await SearchService().sections(query, repo=repo, doc_path=doc_path, max_results=max_results)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    meta.set("results_count", data["results_count"])
    meta.set("query", data["query"])

    returned_tokens = data["returned_tokens"]
    equivalent_tokens = data["equivalent_tokens"]
    if returned_tokens > 0 and equivalent_tokens > 0:
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method="byte_estimate")

    repo_id = data["repo_id"]
    if repo_id:
        meta.set("repo_id", repo_id)

    return wrap_response({"sections": data["sections"]}, meta.build())
