"""Workspace management tools -- group repos, cross-repo operations."""

from sylvan.tools.base import (
    HasDepth,
    HasKindFilter,
    HasLanguageFilter,
    HasPagination,
    HasQuery,
    HasRepo,
    HasSymbol,
    HasWorkspace,
    Tool,
    ToolParams,
    schema_field,
)
from sylvan.tools.base.meta import get_meta


class AddToWorkspace(Tool):
    name = "add_to_workspace"
    category = "meta"
    description = "Add an already-indexed repo to a workspace."

    class Params(HasWorkspace, HasRepo, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.error_codes import RepoNotFoundError, WorkspaceNotFoundError
        from sylvan.services.workspace import WorkspaceService

        svc = WorkspaceService()
        result = await svc.add_repo(p.workspace, p.repo)
        if result is None:
            ws = await WorkspaceService().find(p.workspace)
            if ws is None:
                raise WorkspaceNotFoundError(workspace=p.workspace)
            raise RepoNotFoundError(repo=p.repo)

        ws = await WorkspaceService().with_repos().with_stats().find(p.workspace)
        get_meta().extra("cross_repo_imports_resolved", result["cross_repo_imports_resolved"])
        return {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description or "",
            "created_at": ws.created_at or "",
            "repo_count": len(ws.repos_data or []),
            **ws.stats,
            "repos": ws.repos_data,
        }


class IndexWorkspace(Tool):
    name = "index_workspace"
    category = "indexing"
    description = (
        "BEST WAY to set up multi-repo projects. Indexes multiple folders at once, "
        "groups them into a workspace, and resolves cross-repo imports automatically. "
        "Enables cross-repo search, blast radius, and dependency analysis."
    )

    class Params(HasWorkspace, ToolParams):
        paths: list[str] = schema_field(
            description="List of absolute folder paths to index",
        )
        description: str = schema_field(
            default="",
            description="Workspace description",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.indexing.pipeline.orchestrator import index_folder
        from sylvan.services.workspace import WorkspaceService

        svc = WorkspaceService()
        await svc.create(p.workspace, p.description)

        results = []
        for path in p.paths:
            result = await index_folder(path)
            results.append(result.to_dict())
            if result.repo_id:
                await WorkspaceService().add_repo_by_id(p.workspace, result.repo_id)

        resolved = await WorkspaceService().resolve_cross_repo(p.workspace)

        total_files = sum(r["files_indexed"] for r in results)
        total_symbols = sum(r["symbols_extracted"] for r in results)
        total_sections = sum(r["sections_extracted"] for r in results)

        meta = get_meta()
        meta.extra("repos_indexed", len(results))
        meta.files_indexed(total_files)
        meta.symbols_extracted(total_symbols)
        meta.extra("total_sections", total_sections)
        meta.extra("cross_repo_imports_resolved", resolved)

        return {
            "workspace": p.workspace,
            "repos": results,
            "cross_repo_imports_resolved": resolved,
        }


class WorkspaceSearch(Tool):
    name = "workspace_search"
    category = "meta"
    description = (
        "Search symbols across ALL repos in a workspace simultaneously. "
        "Results from different repos are ranked together. Use this when "
        "working on multi-repo projects (frontend + backend + shared)."
    )

    class Params(HasWorkspace, HasQuery, HasKindFilter, HasLanguageFilter, HasPagination, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.database.orm import Symbol
        from sylvan.error_codes import WorkspaceNotFoundError
        from sylvan.services.workspace import WorkspaceService

        repo_ids = await WorkspaceService().get_repo_ids(p.workspace)
        if not repo_ids:
            raise WorkspaceNotFoundError(workspace=p.workspace)

        query_builder = (
            Symbol.search(p.query)
            .join("files", "files.id = symbols.file_id")
            .join("repos", "repos.id = files.repo_id")
            .where_in("files.repo_id", repo_ids)
        )

        if p.kind:
            query_builder = query_builder.where("symbols.kind", p.kind)
        if p.language:
            query_builder = query_builder.where("symbols.language", p.language)

        query_builder = query_builder.limit(p.max_results)
        symbols = await query_builder.get()

        formatted = []
        for symbol in symbols:
            entry = await symbol.to_summary_dict(include_repo=True)
            del entry["line_start"]
            del entry["line_end"]
            formatted.append(entry)

        meta = get_meta()
        meta.results_count(len(formatted))
        meta.extra("repos_searched", len(repo_ids))

        return {"symbols": formatted}


class WorkspaceBlastRadius(Tool):
    name = "workspace_blast_radius"
    category = "meta"
    description = (
        "Cross-repo blast radius -- shows impact ACROSS repositories. "
        "If you change a shared type, this tells you which files in the "
        "backend AND frontend are affected. Grep cannot do this."
    )

    class Params(HasWorkspace, HasSymbol, HasDepth, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.error_codes import WorkspaceNotFoundError
        from sylvan.services.workspace import WorkspaceService

        repo_ids = await WorkspaceService().get_repo_ids(p.workspace)
        if not repo_ids:
            raise WorkspaceNotFoundError(workspace=p.workspace)

        from sylvan.analysis.impact.cross_repo import cross_repo_blast_radius

        result = await cross_repo_blast_radius(p.symbol_id, repo_ids, max_depth=min(p.depth, 3))

        meta = get_meta()
        meta.extra("confirmed_count", len(result.get("confirmed", [])))
        meta.extra("cross_repo_count", result.get("cross_repo_affected", 0))

        return {**result}


async def add_to_workspace(workspace: str, repo: str, **_kwargs: object) -> dict:
    return await AddToWorkspace().execute({"workspace": workspace, "repo": repo})


async def index_workspace(
    workspace: str,
    paths: list[str],
    description: str = "",
    **_kwargs: object,
) -> dict:
    return await IndexWorkspace().execute(
        {
            "workspace": workspace,
            "paths": paths,
            "description": description,
        }
    )


async def workspace_search(
    workspace: str,
    query: str,
    kind: str | None = None,
    language: str | None = None,
    max_results: int = 20,
    **_kwargs: object,
) -> dict:
    args: dict = {"workspace": workspace, "query": query, "max_results": max_results}
    if kind is not None:
        args["kind"] = kind
    if language is not None:
        args["language"] = language
    return await WorkspaceSearch().execute(args)


async def workspace_blast_radius(
    workspace: str,
    symbol_id: str,
    depth: int = 2,
    **_kwargs: object,
) -> dict:
    return await WorkspaceBlastRadius().execute(
        {
            "workspace": workspace,
            "symbol_id": symbol_id,
            "depth": depth,
        }
    )
