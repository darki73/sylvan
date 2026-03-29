"""MCP tool: search_similar_symbols -- vector similarity search from a source symbol."""

from sylvan.error_codes import SylvanError
from sylvan.services.search import SearchService
from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


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
    meta = get_meta()
    ensure_orm()

    try:
        data = await SearchService().similar(symbol_id, repo=repo, max_results=max_results)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    meta.set("results_count", data["results_count"])
    meta.set("source_symbol", data["source_symbol"])

    returned_tokens = data["returned_tokens"]
    equivalent_tokens = data["equivalent_tokens"]
    if returned_tokens > 0 and equivalent_tokens > 0:
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method="byte_estimate")

    repo_id = data["repo_id"]
    if repo_id:
        meta.set("repo_id", repo_id)

    return wrap_response(
        {"source": data["source"], "similar": data["similar"]},
        meta.build(),
    )
