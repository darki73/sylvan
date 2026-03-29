"""Workspace management tools -- group repos, cross-repo operations."""

from sylvan.database.orm import Symbol
from sylvan.error_codes import RepoNotFoundError, WorkspaceNotFoundError
from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def add_to_workspace(workspace: str, repo: str) -> dict:
    """Add an indexed repository to a workspace.

    Args:
        workspace: Workspace name.
        repo: Repository name.

    Returns:
        Tool response dict with updated workspace info and ``_meta`` envelope.

    Raises:
        WorkspaceNotFoundError: If the workspace does not exist.
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.services.workspace import WorkspaceService

    svc = WorkspaceService()
    result = await svc.add_repo(workspace, repo)
    if result is None:
        ws = await WorkspaceService().find(workspace)
        if ws is None:
            raise WorkspaceNotFoundError(workspace=workspace, _meta=meta.build())
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

    meta.set("cross_repo_imports_resolved", result["cross_repo_imports_resolved"])

    ws = await WorkspaceService().with_repos().with_stats().find(workspace)
    data = {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description or "",
        "created_at": ws.created_at or "",
        "repo_count": len(ws.repos_data or []),
        **ws.stats,
        "repos": ws.repos_data,
    }
    return wrap_response(data, meta.build())


@log_tool_call
async def index_workspace(
    workspace: str,
    paths: list[str],
    description: str = "",
) -> dict:
    """Index multiple folders and group them into a workspace.

    Args:
        workspace: Workspace name to create or update.
        paths: List of absolute folder paths to index.
        description: Optional workspace description.

    Returns:
        Tool response dict with per-repo results and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.indexing.pipeline.orchestrator import index_folder
    from sylvan.services.workspace import WorkspaceService

    svc = WorkspaceService()
    await svc.create(workspace, description)

    results = []
    for path in paths:
        result = await index_folder(path)
        results.append(result.to_dict())
        if result.repo_id:
            await WorkspaceService().add_repo_by_id(workspace, result.repo_id)

    resolved = await WorkspaceService().resolve_cross_repo(workspace)

    total_files = sum(r["files_indexed"] for r in results)
    total_symbols = sum(r["symbols_extracted"] for r in results)
    total_sections = sum(r["sections_extracted"] for r in results)

    meta.set("repos_indexed", len(results))
    meta.set("total_files", total_files)
    meta.set("total_symbols", total_symbols)
    meta.set("total_sections", total_sections)
    meta.set("cross_repo_imports_resolved", resolved)

    return wrap_response(
        {
            "workspace": workspace,
            "repos": results,
            "cross_repo_imports_resolved": resolved,
        },
        meta.build(),
    )


@log_tool_call
async def workspace_blast_radius(
    workspace: str,
    symbol_id: str,
    depth: int = 2,
) -> dict:
    """Cross-repo blast radius -- impact across all repos in a workspace.

    Args:
        workspace: Workspace name.
        symbol_id: The symbol to analyse.
        depth: Import hops to follow (max 3).

    Returns:
        Tool response dict with cross-repo impact data and ``_meta`` envelope.

    Raises:
        WorkspaceNotFoundError: If the workspace is empty or does not exist.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.services.workspace import WorkspaceService

    repo_ids = await WorkspaceService().get_repo_ids(workspace)
    if not repo_ids:
        raise WorkspaceNotFoundError(workspace=workspace, _meta=meta.build())

    from sylvan.analysis.impact.cross_repo import cross_repo_blast_radius

    result = await cross_repo_blast_radius(symbol_id, repo_ids, max_depth=min(depth, 3))

    meta.set("confirmed_count", len(result.get("confirmed", [])))
    meta.set("cross_repo_count", result.get("cross_repo_affected", 0))
    return wrap_response(result, meta.build())


@log_tool_call
async def workspace_search(
    workspace: str,
    query: str,
    kind: str | None = None,
    language: str | None = None,
    max_results: int = 20,
) -> dict:
    """Search symbols across all repos in a workspace.

    Args:
        workspace: Workspace name.
        query: Search query string.
        kind: Filter by symbol kind.
        language: Filter by programming language.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``symbols`` list and ``_meta`` envelope.

    Raises:
        WorkspaceNotFoundError: If the workspace is empty or does not exist.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.services.workspace import WorkspaceService

    repo_ids = await WorkspaceService().get_repo_ids(workspace)
    if not repo_ids:
        raise WorkspaceNotFoundError(workspace=workspace, _meta=meta.build())

    query_builder = (
        Symbol.search(query)
        .join("files", "files.id = symbols.file_id")
        .join("repos", "repos.id = files.repo_id")
        .where_in("files.repo_id", repo_ids)
    )

    if kind:
        query_builder = query_builder.where("symbols.kind", kind)
    if language:
        query_builder = query_builder.where("symbols.language", language)

    query_builder = query_builder.limit(max_results)
    symbols = await query_builder.get()

    formatted = []
    for symbol in symbols:
        entry = await symbol.to_summary_dict(include_repo=True)
        del entry["line_start"]
        del entry["line_end"]
        formatted.append(entry)

    meta.set("results_count", len(formatted))
    meta.set("repos_searched", len(repo_ids))
    return wrap_response({"symbols": formatted}, meta.build())
