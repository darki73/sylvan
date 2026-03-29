"""Workspace service - fluent query builder for workspace data.

Usage::

    # MCP tool: workspace with repos and stats
    ws = await WorkspaceService().with_repos().with_stats().find("my-ws")
    print(ws.name, ws.stats["total_files"])

    # Dashboard: workspace with available repos for adding
    ws = await WorkspaceService().with_repos().with_stats().with_available_repos().find("my-ws")

    # CLI: list all workspaces with repo counts
    workspaces = await WorkspaceService().with_repos().with_stats().get()

    # Mutations
    ws = await WorkspaceService().create("my-ws", description="frontend")
    result = await WorkspaceService().add_repo("my-ws", "sylvan")
    ok = await WorkspaceService().delete("my-ws")
"""

from __future__ import annotations

from sylvan.database.orm import Repo
from sylvan.database.orm.models.workspace import Workspace
from sylvan.services.repository import load_stats


async def load_workspace_repos(ws: Workspace) -> list[dict]:
    """Load per-repo data for a workspace's repos.

    Args:
        ws: Workspace model with repos relation loaded.

    Returns:
        List of dicts with repo id, name, source_path, and stat counts.
    """
    repos_data = []
    for repo in ws.repos:
        stats = await load_stats(repo.id)
        repos_data.append(
            {
                "id": repo.id,
                "name": repo.name,
                "source_path": repo.source_path or "",
                **stats,
            }
        )
    return repos_data


async def load_available_repos(ws_repo_ids: set[int]) -> list[dict]:
    """Load repos not yet in a workspace.

    Args:
        ws_repo_ids: Set of repo IDs already in the workspace.

    Returns:
        List of dicts with id and name for each available repo.
    """
    all_repos = await Repo.where_not(repo_type="library").order_by("name").get()
    return [{"id": r.id, "name": r.name} for r in all_repos if r.id not in ws_repo_ids]


class WorkspaceResult:
    """A Workspace model enriched with optional computed data.

    Model fields (name, description, etc.) are accessible directly
    via attribute proxy. Extra data is None until loaded by the service.
    """

    __slots__ = ("_model", "available_repos", "repos_data", "stats")

    def __init__(self, model: Workspace) -> None:
        self._model = model
        self.repos_data: list[dict] | None = None
        self.stats: dict | None = None
        self.available_repos: list[dict] | None = None

    def __getattr__(self, name: str):
        return getattr(self._model, name)

    def __repr__(self) -> str:
        return f"<WorkspaceResult {self._model.name}>"


class WorkspaceService:
    """Fluent query builder for workspace data.

    Chain ``with_*()`` methods to declare what data to load,
    then call ``get()`` or ``find()`` to execute. Same single-use
    contract as QueryBuilder.
    """

    def __init__(self) -> None:
        self._include_repos = False
        self._include_stats = False
        self._include_available_repos = False

    def with_repos(self) -> WorkspaceService:
        """Load per-repo data (id, name, source_path, file/symbol/section counts)."""
        self._include_repos = True
        return self

    def with_stats(self) -> WorkspaceService:
        """Aggregate stats across all repos (requires with_repos)."""
        self._include_stats = True
        return self

    def with_available_repos(self) -> WorkspaceService:
        """Load repos not yet in this workspace."""
        self._include_available_repos = True
        return self

    async def get(self) -> list[WorkspaceResult]:
        """Execute the query and return all workspaces.

        Returns:
            List of WorkspaceResult with requested data loaded.
        """
        ws_list = await Workspace.query().with_("repos").order_by("name").get()
        return [await self._enrich(ws) for ws in ws_list]

    async def find(self, name: str) -> WorkspaceResult | None:
        """Find a single workspace by name.

        Args:
            name: Workspace name.

        Returns:
            WorkspaceResult with requested data loaded, or None.
        """
        ws = await Workspace.where(name=name).with_("repos").first()
        if ws is None:
            return None
        return await self._enrich(ws)

    async def create(self, name: str, description: str = "") -> WorkspaceResult:
        """Create a workspace, or return existing if name is taken.

        Args:
            name: Unique workspace name.
            description: Optional description.

        Returns:
            WorkspaceResult wrapping the created or existing Workspace.
        """
        from datetime import UTC, datetime

        existing = await Workspace.where(name=name).first()
        if existing is not None:
            return WorkspaceResult(existing)
        ws = await Workspace.create(
            name=name,
            description=description,
            created_at=datetime.now(UTC).isoformat(),
        )
        return WorkspaceResult(ws)

    async def update(
        self,
        name: str,
        new_name: str | None = None,
        description: str | None = None,
    ) -> WorkspaceResult | None:
        """Update workspace name or description.

        Args:
            name: Current workspace name.
            new_name: New name, or None to keep current.
            description: New description, or None to keep current.

        Returns:
            WorkspaceResult wrapping the updated model, or None if not found.
        """
        ws = await Workspace.where(name=name).first()
        if ws is None:
            return None
        if new_name:
            ws.name = new_name
        if description is not None:
            ws.description = description
        await ws.save()
        return WorkspaceResult(ws)

    async def delete(self, name: str) -> bool:
        """Delete a workspace and detach all repos.

        Args:
            name: Workspace name.

        Returns:
            True if deleted, False if not found.
        """
        ws = await Workspace.where(name=name).first()
        if ws is None:
            return False
        await ws.detach("repos")
        await ws.delete()
        return True

    async def add_repo(self, workspace_name: str, repo_name: str) -> dict | None:
        """Add a repo to a workspace and resolve cross-repo imports.

        Args:
            workspace_name: Workspace name.
            repo_name: Repository name.

        Returns:
            Dict with cross_repo_imports_resolved count, or None if not found.
        """
        ws = await Workspace.where(name=workspace_name).first()
        if ws is None:
            return None

        repo = await Repo.where(name=repo_name).first()
        if repo is None:
            return None

        await ws.attach("repos", repo.id)

        resolved = await self.resolve_cross_repo(workspace_name)
        return {"cross_repo_imports_resolved": resolved}

    async def add_repo_by_id(self, workspace_name: str, repo_id: int) -> bool:
        """Add a repo to a workspace by ID.

        Args:
            workspace_name: Workspace name.
            repo_id: Repo primary key.

        Returns:
            True if successful, False if workspace not found.
        """
        ws = await Workspace.where(name=workspace_name).first()
        if ws is None:
            return False
        await ws.attach("repos", repo_id)
        return True

    async def remove_repo_by_id(self, workspace_name: str, repo_id: int) -> bool:
        """Remove a repo from a workspace by ID.

        Args:
            workspace_name: Workspace name.
            repo_id: Repo primary key.

        Returns:
            True if successful, False if workspace not found.
        """
        ws = await Workspace.where(name=workspace_name).first()
        if ws is None:
            return False
        await ws.detach("repos", repo_id)
        return True

    async def get_repo_ids(self, name: str) -> list[int]:
        """Get repo IDs belonging to a workspace.

        Args:
            name: Workspace name.

        Returns:
            List of repo IDs, empty if workspace not found.
        """
        ws = await Workspace.where(name=name).with_("repos").first()
        if ws is None:
            return []
        return [repo.id for repo in ws.repos]

    async def resolve_cross_repo(self, name: str) -> int:
        """Resolve cross-repo imports for all repos in a workspace.

        Args:
            name: Workspace name.

        Returns:
            Number of cross-repo imports resolved.
        """
        repo_ids = await self.get_repo_ids(name)
        if not repo_ids:
            return 0
        from sylvan.analysis.impact.cross_repo import resolve_cross_repo_imports

        return await resolve_cross_repo_imports(repo_ids)

    async def _enrich(self, ws: Workspace) -> WorkspaceResult:
        """Wrap a Workspace model and load requested extra data.

        Args:
            ws: The Workspace model instance with repos relation loaded.

        Returns:
            WorkspaceResult with repos/stats/available_repos populated if requested.
        """
        result = WorkspaceResult(ws)
        if self._include_repos:
            result.repos_data = await load_workspace_repos(ws)
        if self._include_stats and result.repos_data is not None:
            total_files = sum(r["files"] for r in result.repos_data)
            total_symbols = sum(r["symbols"] for r in result.repos_data)
            total_sections = sum(r["sections"] for r in result.repos_data)
            result.stats = {
                "total_files": total_files,
                "total_symbols": total_symbols,
                "total_sections": total_sections,
            }
        if self._include_available_repos:
            ws_repo_ids = {r["id"] for r in (result.repos_data or [])}
            result.available_repos = await load_available_repos(ws_repo_ids)
        return result
