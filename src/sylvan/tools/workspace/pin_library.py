"""MCP tool: pin a specific library version to a workspace."""

from sylvan.database.orm import Repo
from sylvan.database.orm.runtime.connection_manager import get_backend
from sylvan.database.workspace import (
    async_add_repo_to_workspace,
    async_get_workspace,
)
from sylvan.error_codes import RepoNotFoundError, WorkspaceNotFoundError
from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


@log_tool_call
async def pin_library(workspace: str, library: str) -> dict:
    """Pin a specific library version to a workspace.

    The library must already be indexed via ``add_library``. Once pinned,
    searching within this workspace will include that library version's
    symbols and sections.

    Args:
        workspace: Workspace name.
        library: Library display name including version (e.g. ``"numpy@2.2.2"``).

    Returns:
        Tool response dict confirming the pin.

    Raises:
        WorkspaceNotFoundError: If the workspace does not exist.
        RepoNotFoundError: If the library version is not indexed.
    """
    meta = MetaBuilder()
    backend = get_backend()

    ws = await async_get_workspace(backend, workspace)
    if ws is None:
        raise WorkspaceNotFoundError(workspace=workspace, _meta=meta.build())

    repo = await Repo.where(name=library).where(repo_type="library").first()
    if repo is None:
        raise RepoNotFoundError(
            repo=library,
            detail=f"Library '{library}' is not indexed. Run add_library first.",
            _meta=meta.build(),
        )

    await async_add_repo_to_workspace(backend, ws["id"], repo.id)

    meta.set("workspace", workspace)
    meta.set("library", library)
    meta.set("repo_id", repo.id)
    return wrap_response({
        "status": "pinned",
        "workspace": workspace,
        "library": library,
    }, meta.build())
