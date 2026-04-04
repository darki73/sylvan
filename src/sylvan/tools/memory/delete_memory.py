"""MCP tool: delete_memory, remove a stored memory."""

from sylvan.tools.base import HasRepo, Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class DeleteMemory(Tool):
    name = "delete_memory"
    category = "meta"
    description = (
        "Delete a memory that is no longer accurate or relevant. Use the memory ID from search or retrieve results."
    )

    class Params(HasRepo, ToolParams):
        id: int = schema_field(
            description="Memory ID to delete",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.memory import MemoryService

        result = await MemoryService().delete(p.repo, p.id)
        meta = get_meta()
        meta.repo(p.repo)
        meta.extra("status", result["status"])
        return result
