"""MCP tool: list_repos -- list all indexed repositories."""

from sylvan.tools.base import Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class ListRepos(Tool):
    name = "indexed_repos"
    category = "meta"
    description = "Lists all indexed repositories with file count, symbol count, source path, and indexing timestamp."

    class Params(ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.repository import RepositoryService

        repos = await RepositoryService().with_stats().get()
        get_meta().results_count(len(repos))
        return {
            "repos": [
                {
                    "id": r.id,
                    "name": r.name,
                    "source_path": r.source_path,
                    "github_url": r.github_url,
                    "indexed_at": r.indexed_at,
                    "git_head": r.git_head,
                    "file_count": r.stats["files"],
                    "symbol_count": r.stats["symbols"],
                }
                for r in repos
            ],
        }


async def list_repos(**_kwargs: object) -> dict:
    return await ListRepos().execute({})
