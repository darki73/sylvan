"""MCP tool: get_dependency_graph -- file-level import graph traversal."""

from sylvan.tools.support.response import clamp, ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


@log_tool_call
async def get_dependency_graph(
    repo: str,
    file_path: str,
    direction: str = "both",
    depth: int = 1,
) -> dict:
    """Build a file-level import dependency graph around a target file.

    Uses resolved import data from the ``file_imports`` table to traverse
    the graph in the requested direction(s).

    Args:
        repo: Repository name.
        file_path: The file to centre the graph on.
        direction: Traversal direction: ``"imports"``, ``"importers"``, or ``"both"``.
        depth: How many hops to follow (1-3).

    Returns:
        Tool response dict with ``nodes`` (file details) and ``edges``
        (import relationships).

    Raises:
        RepoNotFoundError: If the repository is not indexed.
        IndexFileNotFoundError: If the target file is not in the index.
    """
    meta = get_meta()
    depth = clamp(depth, 1, 3)
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.analysis import AnalysisService

        result = await AnalysisService().dependency_graph(repo, file_path, direction=direction, depth=depth)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    meta.set("node_count", result.pop("node_count"))
    meta.set("edge_count", result.pop("edge_count"))
    meta.set("direction", result.pop("direction"))
    meta.set("depth", result.pop("depth"))

    return wrap_response(result, meta.build())
