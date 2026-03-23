"""MCP tool: index_folder -- index a local folder."""

from sylvan.context import get_context
from sylvan.indexing.pipeline.orchestrator import index_folder as _index_folder
from sylvan.tools.support.response import MetaBuilder, _staleness_cache, log_tool_call, wrap_response


@log_tool_call
async def index_folder(
    path: str,
    name: str | None = None,
) -> dict:
    """Index a local folder for code symbol retrieval.

    Delegates to the indexing orchestrator, then clears any cached
    staleness state for the repo so subsequent tool calls re-check.

    Args:
        path: Absolute path to the folder to index.
        name: Display name (defaults to folder name).

    Returns:
        Tool response dict with indexing stats and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    result = await _index_folder(path, name=name)

    _staleness_cache.pop(result.repo_id, None)
    get_context().cache.clear()

    meta.set("repo", result.repo_name)
    meta.set("files_indexed", result.files_indexed)
    meta.set("symbols_extracted", result.symbols_extracted)

    return wrap_response(result.to_dict(), meta.build())
