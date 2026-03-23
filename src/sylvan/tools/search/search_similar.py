"""MCP tool: search_similar_symbols -- vector similarity search from a source symbol."""

from sylvan.database.orm import Repo, Symbol
from sylvan.error_codes import RepoNotFoundError, SymbolNotFoundError
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def search_similar_symbols(
    symbol_id: str,
    repo: str | None = None,
    max_results: int = 10,
) -> dict:
    """Find symbols semantically similar to a given source symbol.

    Looks up the source symbol's signature and docstring, then runs a
    vector similarity search to find related code across the index.

    Args:
        symbol_id: The stable identifier of the source symbol.
        repo: Optional repository name to restrict results to.
        max_results: Maximum number of similar symbols to return.

    Returns:
        Tool response dict with ``source`` summary, ``similar`` list,
        and ``_meta`` envelope.

    Raises:
        SymbolNotFoundError: If the source symbol does not exist.
        RepoNotFoundError: If the repo filter does not match any indexed repo.
    """
    meta = MetaBuilder()
    ensure_orm()

    max_results = clamp(max_results, 1, 100)

    source = await Symbol.where(symbol_id=symbol_id).first()
    if source is None:
        raise SymbolNotFoundError(symbol_id=symbol_id, _meta=meta.build())

    # Build search text from signature + docstring
    parts: list[str] = []
    if source.signature:
        parts.append(source.signature)
    if source.docstring:
        parts.append(source.docstring)
    if not parts:
        parts.append(source.name)
    search_text = " ".join(parts)

    # Run vector similarity search
    query_builder = Symbol.similar_to(search_text, k=max_results + 1)

    if repo:
        repo_obj = await Repo.where(name=repo).first()
        if repo_obj is None:
            raise RepoNotFoundError(repo=repo, _meta=meta.build())
        query_builder = query_builder.in_repo(repo)

    results = await query_builder.get()

    # Format results, excluding the source symbol itself
    similar: list[dict] = []
    for symbol in results:
        if symbol.symbol_id == symbol_id:
            continue
        entry = await symbol.to_summary_dict(include_repo=True)
        entry["line"] = entry.pop("line_start")
        del entry["line_end"]
        similar.append(entry)
        if len(similar) >= max_results:
            break

    source_summary = await source.to_summary_dict(include_repo=True)

    meta.set("results_count", len(similar))
    meta.set("source_symbol", symbol_id)

    # Token efficiency
    returned_tokens = sum(len(str(e)) // 4 for e in similar)
    unique_files = {e.get("file") for e in similar if e.get("file")}
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

    return wrap_response(
        {"source": source_summary, "similar": similar},
        meta.build(),
    )
