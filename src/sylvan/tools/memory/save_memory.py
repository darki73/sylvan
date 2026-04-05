"""MCP tool: save_memory, store agent project knowledge."""

from sylvan.tools.base import HasRepo, Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class SaveMemory(Tool):
    name = "remember_this"
    category = "meta"
    description = (
        "Saves project context that would be lost between sessions: decisions, "
        "root causes, business constraints, architecture rationale. "
        "Vector-searchable by meaning, portable across agents and machines. "
        "Auto-deduplicates similar content."
    )

    class Params(HasRepo, ToolParams):
        content: str = schema_field(
            description="The insight, decision, or context to save",
        )
        tags: list[str] = schema_field(
            default=[],
            description="Tags for categorization (e.g. ['architecture', 'decision'])",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.memory import MemoryService

        result = await MemoryService().save(p.repo, p.content, p.tags)
        meta = get_meta()
        meta.repo(p.repo)
        meta.extra("status", result["status"])
        return result
