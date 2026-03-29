"""MCP tool: index_folder -- index a local folder."""

from sylvan.tools.support.response import get_meta, log_tool_call, wrap_response


@log_tool_call
async def index_folder(
    path: str,
    name: str | None = None,
) -> dict:
    """Index a local folder for code symbol retrieval.

    Delegates to the indexing service, then returns stats about the
    indexed repo.

    Args:
        path: Absolute path to the folder to index.
        name: Display name (defaults to folder name).

    Returns:
        Tool response dict with indexing stats and ``_meta`` envelope.
    """
    meta = get_meta()

    from sylvan.services.indexing import index_folder as _svc

    result = await _svc(path, name=name)

    meta.set("repo", result.get("repo", ""))
    meta.set("files_indexed", result.get("files_indexed", 0))
    meta.set("symbols_extracted", result.get("symbols_extracted", 0))

    return wrap_response(result, meta.build())
