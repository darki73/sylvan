"""MCP tool: find_importers -- find files that import a given file."""

from sylvan.tools.support.response import clamp, ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def find_importers(repo: str, file_path: str, max_results: int = 50) -> dict:
    """Find all files that import a given file.

    Args:
        repo: Repository name.
        file_path: The file to find importers of.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``importers`` list and ``_meta`` envelope.

    Raises:
        IndexFileNotFoundError: If the target file does not exist in the repo's index.
    """
    meta = get_meta()
    max_results = clamp(max_results, 1, 1000)
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.analysis import AnalysisService

        result = await AnalysisService().find_importers(repo, file_path, max_results=max_results)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    meta.set("count", len(result["importers"]))
    return wrap_response(result, meta.build())


@log_tool_call
async def batch_find_importers(repo: str, file_paths: list[str], max_results: int = 20) -> dict:
    """Find importers for multiple files in one call.

    Args:
        repo: Repository name.
        file_paths: List of file paths to find importers of.
        max_results: Maximum importers per file.

    Returns:
        Tool response dict with ``results`` list (one per file),
        ``not_found`` list, and ``_meta`` envelope.
    """
    meta = get_meta()
    max_results = clamp(max_results, 1, 100)
    ensure_orm()

    from sylvan.services.analysis import AnalysisService

    data = await AnalysisService().batch_find_importers(repo, file_paths, max_results=max_results)
    meta.set("found", data["found"])
    meta.set("not_found", len(data["not_found"]))
    meta.set("total_importers", data["total_importers"])
    return wrap_response({"results": data["results"], "not_found": data["not_found"]}, meta.build())
