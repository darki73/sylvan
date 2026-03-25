"""MCP tool: search_symbols -- session-aware search of indexed code symbols."""

import json

from sylvan.database.orm import Repo, Symbol
from sylvan.error_codes import EmptyQueryError
from sylvan.session.tracker import get_session
from sylvan.tools.support.response import MetaBuilder, check_staleness, clamp, ensure_orm, log_tool_call, wrap_response
from sylvan.tools.support.token_counting import count_tokens


def _estimate_entry_tokens(entry: dict) -> int:
    """Estimate the token count of a result entry when serialised.

    Args:
        entry: A single search result dict.

    Returns:
        Estimated token count (tiktoken if available, else byte ratio).
    """
    text = json.dumps(entry, default=str)
    token_count = count_tokens(text)
    if token_count is not None:
        return token_count
    return max(1, len(text) // 4)


async def _rerank_with_session(
    results: list,
    seen_ids: set[str],
    session: object,
) -> tuple[list[dict], list[dict]]:
    """Separate results into unseen (boosted by file relevance) and already-seen.

    Args:
        results: ORM symbol results from the search query.
        seen_ids: Set of symbol IDs already retrieved this session.
        session: The session tracker instance.

    Returns:
        Two-tuple of (ordered_results, already_seen_results).
    """
    reranked = []
    already_seen = []

    for symbol in results:
        entry = await symbol.to_summary_dict(include_repo=True)
        entry["line"] = entry.pop("line_start")
        del entry["line_end"]

        if symbol.symbol_id in seen_ids:
            entry["_already_retrieved"] = True
            already_seen.append(entry)
        else:
            boost = session.compute_file_boost(entry["file"])
            reranked.append((boost, entry))

    reranked.sort(key=lambda x: -x[0])
    ordered = [r for _, r in reranked]
    ordered.extend(already_seen)
    return ordered, already_seen


def _apply_token_budget(formatted: list[dict], token_budget: int) -> tuple[list[dict], int]:
    """Greedy-pack results until the token budget is exhausted.

    Args:
        formatted: Ordered list of result dicts to pack.
        token_budget: Maximum token count to include.

    Returns:
        Two-tuple of (packed_results, tokens_used).
    """
    budgeted = []
    tokens_used = 0
    for entry in formatted:
        entry_tokens = _estimate_entry_tokens(entry)
        if tokens_used + entry_tokens > token_budget and budgeted:
            break
        budgeted.append(entry)
        tokens_used += entry_tokens
    return budgeted, tokens_used


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
    from sylvan.context import get_context

    meta = MetaBuilder()
    ctx = get_context()
    session = ctx.session if ctx.session else get_session()
    session.record_query(query, "search_symbols")
    max_results = clamp(max_results, 1, 1000)

    ensure_orm()

    if not query or not query.strip():
        raise EmptyQueryError(_meta=meta.build())

    fetch_count = max_results * 2 if session.get_seen_symbol_ids() else max_results

    query_builder = Symbol.search(query)

    if repo:
        query_builder = query_builder.in_repo(repo)
    if kind:
        query_builder = query_builder.where(kind=kind)
    if language:
        query_builder = query_builder.where(language=language)
    if file_pattern:
        query_builder = query_builder.join("files", "files.id = symbols.file_id").where_glob("files.path", file_pattern)

    query_builder = query_builder.limit(fetch_count)
    results = await query_builder.get()

    seen_ids = session.get_seen_symbol_ids()
    ordered, already_seen = await _rerank_with_session(results, seen_ids, session)

    formatted = ordered[:max_results]

    tokens_used = 0
    if token_budget is not None and token_budget > 0:
        formatted, tokens_used = _apply_token_budget(formatted, token_budget)

    meta.set("results_count", len(formatted))
    meta.set("query", query)
    meta.set("already_seen_deprioritized", len(already_seen))

    if token_budget is not None and token_budget > 0:
        meta.set("tokens_used", tokens_used)
        meta.set("tokens_remaining", max(0, token_budget - tokens_used))

    # Token efficiency: returned tokens vs equivalent full-file reads
    returned_tokens = sum(_estimate_entry_tokens(e) for e in formatted)
    unique_files = {e.get("file") for e in formatted if e.get("file")}
    equivalent_tokens = 0
    for symbol in results:
        file_path = await symbol._resolve_file_path()
        if file_path in unique_files:
            unique_files.discard(file_path)
            file_rec = symbol.file
            if file_rec and file_rec.byte_size:
                equivalent_tokens += file_rec.byte_size // 4
    if returned_tokens > 0 and equivalent_tokens > 0:
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method="byte_estimate")

    repo_obj = None
    if repo:
        repo_obj = await Repo.where(name=repo).first()
        if repo_obj:
            meta.set("repo_id", repo_obj.id)

    result = wrap_response({"symbols": formatted}, meta.build())

    if repo_obj:
        await check_staleness(repo_obj.id, result)

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
    meta = MetaBuilder()
    ensure_orm()

    session = get_session()
    all_results = []
    equivalent = 0

    for q in queries:
        query_text = q.get("query", "")
        if not query_text or not query_text.strip():
            all_results.append({"query": query_text, "symbols": [], "error": "empty_query"})
            continue

        session.record_query(query_text, "batch_search_symbols")

        q_repo = q.get("repo", repo)
        q_kind = q.get("kind")
        q_language = q.get("language")
        q_max = clamp(q.get("max_results", max_results_per_query), 1, 100)

        query_builder = Symbol.search(query_text)
        if q_repo:
            query_builder = query_builder.in_repo(q_repo)
        if q_kind:
            query_builder = query_builder.where(kind=q_kind)
        if q_language:
            query_builder = query_builder.where(language=q_language)

        results = await query_builder.limit(q_max).get()

        formatted = []
        for symbol in results:
            formatted.append(
                {
                    "symbol_id": symbol.symbol_id,
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "file": await symbol._resolve_file_path(),
                    "signature": symbol.signature or "",
                }
            )

        unique_files = set()
        for symbol in results:
            fp = await symbol._resolve_file_path()
            if fp:
                unique_files.add(fp)
            file_rec = symbol.file
            if file_rec and file_rec.byte_size and fp in unique_files:
                unique_files.discard(fp)
                equivalent += file_rec.byte_size // 4

        all_results.append({"query": query_text, "count": len(formatted), "symbols": formatted})

    returned = sum(_estimate_entry_tokens(e) for r in all_results for e in r.get("symbols", []))
    if returned > 0 and equivalent > 0:
        meta.record_token_efficiency(returned, equivalent, method="byte_estimate")

    meta.set("queries", len(queries))
    meta.set("total_results", sum(r.get("count", 0) for r in all_results))
    return wrap_response({"results": all_results}, meta.build())
