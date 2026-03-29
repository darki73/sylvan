"""MCP tool: search_symbols -- session-aware search of indexed code symbols."""

from sylvan.error_codes import SylvanError
from sylvan.services.search import SearchService
from sylvan.tools.support.response import (
    check_staleness,
    ensure_orm,
    get_meta,
    log_tool_call,
    wrap_response,
)


@log_tool_call
async def search_symbols(
    query: str,
    repo: str | None = None,
    kind: str | None = None,
    language: str | None = None,
    file_pattern: str | None = None,
    max_results: int = 20,
    token_budget: int | None = None,
) -> dict:
    """Search indexed symbols by name, signature, docstring, or keywords.

    Session-aware: deprioritises already-retrieved symbols and boosts
    symbols in files the agent is currently working with.

    Args:
        query: Search query -- symbol name, keyword, or description.
        repo: Filter to a specific repository name.
        kind: Filter by symbol kind (function, class, method, etc.).
        language: Filter by programming language.
        file_pattern: Glob pattern to filter by file path.
        max_results: Maximum number of results to return.
        token_budget: Optional token budget for greedy result packing.

    Returns:
        Tool response dict with ``symbols`` list and ``_meta`` envelope.

    Raises:
        EmptyQueryError: If the query is empty or whitespace-only.
    """
    meta = get_meta()
    ensure_orm()

    svc = SearchService().with_session_reranking()
    if token_budget is not None and token_budget > 0:
        svc = svc.with_token_budget(token_budget)

    try:
        data = await svc.symbols(
            query,
            repo=repo,
            kind=kind,
            language=language,
            file_pattern=file_pattern,
            max_results=max_results,
        )
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    meta.set("results_count", data["results_count"])
    meta.set("query", data["query"])
    meta.set("already_seen_deprioritized", data["already_seen_deprioritized"])

    if data["token_budget"] is not None and data["token_budget"] > 0:
        meta.set("tokens_used", data["tokens_used"])
        meta.set("tokens_remaining", max(0, data["token_budget"] - data["tokens_used"]))

    returned_tokens = data["returned_tokens"]
    equivalent_tokens = data["equivalent_tokens"]
    if returned_tokens > 0 and equivalent_tokens > 0:
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method="byte_estimate")

    repo_id = data["repo_id"]
    if repo_id:
        meta.set("repo_id", repo_id)

    result = wrap_response({"symbols": data["symbols"]}, meta.build())

    if repo_id:
        await check_staleness(repo_id, result)

    return result


@log_tool_call
async def batch_search_symbols(
    queries: list[dict],
    repo: str | None = None,
    max_results_per_query: int = 10,
) -> dict:
    """Run multiple symbol searches in one call.

    Each query object can override ``repo``, ``kind``, ``language``, and
    ``max_results``.  Results are returned grouped by query.

    Args:
        queries: List of query dicts, each with at least a ``query`` key.
            Optional keys: ``repo``, ``kind``, ``language``, ``max_results``.
        repo: Default repo filter applied to all queries.
        max_results_per_query: Default max results per query.

    Returns:
        Tool response dict with ``results`` list (one entry per query)
        and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    data = await SearchService().batch_symbols(queries, repo=repo, max_results_per_query=max_results_per_query)

    returned = data["returned_tokens"]
    equivalent = data["equivalent_tokens"]
    if returned > 0 and equivalent > 0:
        meta.record_token_efficiency(returned, equivalent, method="byte_estimate")

    meta.set("queries", data["queries_count"])
    meta.set("total_results", data["total_results"])
    return wrap_response({"results": data["results"]}, meta.build())
