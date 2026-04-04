"""MCP tool: retrieve_memory, direct lookup of a stored memory."""

from sylvan.tools.base import HasRepo, Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class RetrieveMemory(Tool):
    name = "retrieve_memory"
    category = "retrieval"
    description = (
        "Retrieve a specific memory by its ID. Use when you have a memory ID "
        "from search results and want to see the full content."
    )

    class Params(HasRepo, ToolParams):
        id: int = schema_field(
            description="Memory ID (from save_memory or search_memory results)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.memory import MemoryService

        result = await MemoryService().retrieve(p.repo, p.id)
        meta = get_meta()
        meta.repo(p.repo)
        return result
