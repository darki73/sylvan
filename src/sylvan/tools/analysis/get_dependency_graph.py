"""MCP tool: get_dependency_graph -- file-level import graph traversal."""

from __future__ import annotations

from sylvan.database.orm import FileImport, FileRecord, Symbol
from sylvan.error_codes import IndexFileNotFoundError, RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response


async def _bfs_forward(
    start_id: int,
    max_depth: int,
    nodes: set[int],
    edges: list[tuple[int, int]],
) -> None:
    """BFS forward through imports (what does this file import?).

    Args:
        start_id: Starting file ID.
        max_depth: Maximum traversal depth.
        nodes: Accumulator set of visited file IDs.
        edges: Accumulator list of (source, target) file ID pairs.
    """
    frontier = {start_id}
    nodes.add(start_id)

    for _depth in range(max_depth):
        if not frontier:
            break

        next_frontier: set[int] = set()
        for file_id in frontier:
            imports = await (
                FileImport.query()
                .select("DISTINCT file_imports.resolved_file_id")
                .where("file_imports.file_id", file_id)
                .where_not_null("file_imports.resolved_file_id")
                .get()
            )
            for imp in imports:
                target_id = imp.resolved_file_id
                edges.append((file_id, target_id))
                if target_id not in nodes:
                    nodes.add(target_id)
                    next_frontier.add(target_id)

        frontier = next_frontier


async def _bfs_reverse(
    start_id: int,
    max_depth: int,
    nodes: set[int],
    edges: list[tuple[int, int]],
) -> None:
    """BFS reverse through imports (what imports this file?).

    Args:
        start_id: Starting file ID.
        max_depth: Maximum traversal depth.
        nodes: Accumulator set of visited file IDs.
        edges: Accumulator list of (source, target) file ID pairs.
    """
    frontier = {start_id}
    nodes.add(start_id)

    for _depth in range(max_depth):
        if not frontier:
            break

        next_frontier: set[int] = set()
        for target_id in frontier:
            importers = await (
                FileImport.query()
                .select("DISTINCT file_imports.file_id")
                .where("file_imports.resolved_file_id", target_id)
                .get()
            )
            for imp in importers:
                source_id = imp.file_id
                edges.append((source_id, target_id))
                if source_id not in nodes:
                    nodes.add(source_id)
                    next_frontier.add(source_id)

        frontier = next_frontier


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
        depth: How many hops to follow (1--3).

    Returns:
        Tool response dict with ``nodes`` (file details) and ``edges``
        (import relationships).

    Raises:
        RepoNotFoundError: If the repository is not indexed.
        IndexFileNotFoundError: If the target file is not in the index.
    """
    meta = MetaBuilder()
    depth = clamp(depth, 1, 3)
    ensure_orm()

    from sylvan.database.orm import Repo

    repo_obj = await Repo.where(name=repo).first()
    if not repo_obj:
        raise RepoNotFoundError(f"Repository '{repo}' is not indexed.", repo_name=repo, _meta=meta.build())

    target = await (
        FileRecord.query()
        .join("repos", "repos.id = files.repo_id")
        .where("repos.name", repo)
        .where("files.path", file_path)
        .first()
    )
    if target is None:
        raise IndexFileNotFoundError(file_path=file_path, _meta=meta.build())

    if direction not in ("imports", "importers", "both"):
        direction = "both"

    nodes: set[int] = set()
    edges: list[tuple[int, int]] = []

    if direction in ("imports", "both"):
        await _bfs_forward(target.id, depth, nodes, edges)

    if direction in ("importers", "both"):
        await _bfs_reverse(target.id, depth, nodes, edges)

    # Build node details
    node_details: dict[str, dict] = {}
    id_to_path: dict[int, str] = {}
    for file_id in nodes:
        f = await FileRecord.find(file_id)
        if f:
            sym_count = await Symbol.where(file_id=f.id).count()
            node_details[f.path] = {
                "language": f.language,
                "symbol_count": sym_count,
                "is_target": f.id == target.id,
            }
            id_to_path[f.id] = f.path

    # Deduplicate edges and convert to paths
    seen_edges: set[tuple[str, str]] = set()
    path_edges = []
    for src_id, tgt_id in edges:
        src_path = id_to_path.get(src_id)
        tgt_path = id_to_path.get(tgt_id)
        if src_path and tgt_path:
            key = (src_path, tgt_path)
            if key not in seen_edges:
                seen_edges.add(key)
                path_edges.append({"from": src_path, "to": tgt_path})

    meta.set("node_count", len(node_details))
    meta.set("edge_count", len(path_edges))
    meta.set("direction", direction)
    meta.set("depth", depth)

    return wrap_response(
        {
            "target": file_path,
            "nodes": node_details,
            "edges": path_edges,
        },
        meta.build(),
    )
