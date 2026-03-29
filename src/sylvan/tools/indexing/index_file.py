"""MCP tool: index_file -- surgical single-file reindex."""

from sylvan.tools.support.response import ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def index_file(
    repo: str,
    file_path: str,
) -> dict:
    """Reindex a single file without touching the rest of the repo.

    Much cheaper than index_folder when only one file has changed.

    Args:
        repo: Repository name (as shown in list_repos).
        file_path: Relative path within the repo (e.g., "src/main.py").

    Returns:
        Tool response dict with indexing stats and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.indexing import index_file as _svc

        result = await _svc(repo, file_path)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    if "error" in result:
        return wrap_response(result, meta.build())

    meta.set("status", result.get("status", "updated"))
    meta.set("symbols_extracted", result.get("symbols_extracted", 0))

    return wrap_response(result, meta.build())
