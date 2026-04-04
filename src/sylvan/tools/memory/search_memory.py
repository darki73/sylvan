"""MCP tool: search_memory, semantic search over project memories."""

from sylvan.tools.base import HasPagination, HasQuery, HasRepo, Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class SearchMemory(Tool):
    name = "search_memory"
    category = "search"
    description = (
        "Check this BEFORE making assumptions about project history, prior "
        "decisions, or past issues. If the user references something from a "
        "previous session, or you are about to suggest an approach for something "
        "that feels like it has history, search here first. Returns project "
        "memories ranked by semantic relevance: context that was saved because "
        "it mattered and would be lost between sessions. "
        "Uses vector similarity, not keyword matching, so natural language queries "
        "work well. This searches project-scoped knowledge, not your harness memory."
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
