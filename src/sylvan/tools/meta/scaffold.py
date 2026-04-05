"""MCP tool: scaffold -- generate sylvan/ directory and agent instructions."""

from sylvan.tools.base import HasRepo, Tool, ToolParams, schema_field


class Scaffold(Tool):
    name = "generate_project_docs"
    category = "meta"
    description = (
        "Generates a sylvan/ project context directory with architecture docs, "
        "quality reports, dependency maps, and an agent instruction file "
        "(CLAUDE.md or .cursorrules). Creates planning directories for "
        "future/working/completed tasks."
    )

    class Params(HasRepo, ToolParams):
        agent: str = schema_field(
            default="claude",
            description="Agent format for instruction file",
            enum=["claude", "cursor", "copilot", "generic"],
        )
        root: str | None = schema_field(
            default=None,
            description="Override project root path",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.meta import scaffold as _svc
        from sylvan.tools.base.meta import get_meta

        result = await _svc(p.repo, agent=p.agent, root=p.root)
        meta = get_meta()
        meta.extra("status", result.get("status", "error"))
        meta.extra("files_created", result.get("files_created", 0))
        return {**result}


async def scaffold(
    repo: str,
    agent: str = "claude",
    root: str | None = None,
    **_kwargs: object,
) -> dict:
    return await Scaffold().execute({"repo": repo, "agent": agent, "root": root})
