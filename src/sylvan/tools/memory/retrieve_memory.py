"""MCP tool: retrieve_memory, direct lookup of a stored memory."""

from sylvan.tools.base import HasRepo, Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class RetrieveMemory(Tool):
    name = "get_memory"
    category = "retrieval"
    description = "Retrieves a specific memory by ID. Returns the full content, tags, and timestamps."

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
