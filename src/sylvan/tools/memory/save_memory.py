"""MCP tool: save_memory, store agent project knowledge."""

from sylvan.tools.base import HasRepo, Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class SaveMemory(Tool):
    name = "save_memory"
    category = "meta"
    description = (
        "Proactively save context that would be lost when this session ends. "
        "Call this when: (1) the user explains WHY something is done a certain "
        "way, (2) a debugging session reveals a non-obvious root cause, "
        "(3) an architecture or design decision is made with reasoning, "
        "(4) the user shares business context, constraints, or deadlines, "
        "(5) you discover something surprising about the codebase that isn't "
        "obvious from the code itself. Keep it concise, summarize the insight, "
        "not the conversation. Do not save things derivable from code or git log. "
        "Duplicates are handled automatically, similar content updates the "
        "existing memory instead of creating a new one. "
        "Use this for project-specific context tied to a repository. "
        "Your harness memory is better for personal preferences across all projects. "
        "This is faster and more capable for project knowledge: "
        "vector-searchable, portable across tools and machines, zero inference cost."
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
