"""MCP tool: remove_repo -- delete an indexed repository and all its data."""

from sylvan.tools.base import HasRepo, Tool, ToolParams


class RemoveRepo(Tool):
    name = "delete_repo_index"
    category = "meta"
    description = (
        "Permanently deletes a repository's index and all associated data: "
        "files, symbols, sections, imports, quality records, references. Cannot be undone."
    )

    class Params(HasRepo, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.repository import RepositoryService
        from sylvan.tools.base.meta import get_meta

        result = await RepositoryService().remove(p.repo)
        meta = get_meta()
        meta.repo(result["repo"])
        meta.repo_id(result["repo_id"])
        return {
            "status": "removed",
            "repo": result["repo"],
        }


async def remove_repo(repo: str, **_kwargs: object) -> dict:
    return await RemoveRepo().execute({"repo": repo})
