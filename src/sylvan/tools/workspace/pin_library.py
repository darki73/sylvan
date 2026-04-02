"""MCP tool: pin_library -- pin a specific library version to a workspace."""

from sylvan.tools.base import HasWorkspace, Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class PinLibrary(Tool):
    name = "pin_library"
    category = "meta"
    description = (
        "Pin a specific library version to a workspace. The library must "
        "already be indexed via add_library. Once pinned, workspace_search "
        "includes that library version's symbols. Use this to give each "
        "project access to the exact library versions it depends on."
    )

    class Params(HasWorkspace, ToolParams):
        library: str = schema_field(
            description="Library display name with version (e.g., 'numpy@2.2.2')",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.database.orm import Repo
        from sylvan.error_codes import RepoNotFoundError, WorkspaceNotFoundError
        from sylvan.services.workspace import WorkspaceService

        ws = await WorkspaceService().find(p.workspace)
        if ws is None:
            raise WorkspaceNotFoundError(workspace=p.workspace)

        repo = await Repo.where(name=p.library).where(repo_type="library").first()
        if repo is None:
            raise RepoNotFoundError(
                repo=p.library,
                detail=f"Library '{p.library}' is not indexed. Run add_library first.",
            )

        await WorkspaceService().add_repo_by_id(p.workspace, repo.id)

        meta = get_meta()
        meta.extra("workspace", p.workspace)
        meta.extra("library", p.library)
        meta.repo_id(repo.id)

        return {
            "status": "pinned",
            "workspace": p.workspace,
            "library": p.library,
        }


async def pin_library(workspace: str, library: str, **_kwargs: object) -> dict:
    return await PinLibrary().execute({"workspace": workspace, "library": library})
