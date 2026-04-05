"""MCP tool: search_memory, semantic search over project memories."""

from sylvan.tools.base import HasPagination, HasQuery, HasRepo, Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class SearchMemory(Tool):
    name = "recall_previous_sessions"
    category = "search"
    description = (
        "Searches project memories by semantic similarity, not keywords. Returns "
        "past decisions, root causes, and context ranked by relevance. Finds "
        "matches even when the query uses different words than what was saved."
    )

    class Params(HasRepo, HasQuery, HasPagination, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.memory import MemoryService

        result = await MemoryService().search(p.repo, p.query, p.max_results)
        meta = get_meta()
        meta.repo(p.repo)
        meta.results_count(result["count"])
        meta.query(p.query)
        return result
