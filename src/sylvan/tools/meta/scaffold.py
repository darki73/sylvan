"""MCP tool: scaffold -- generate sylvan/ directory and agent instructions."""

from sylvan.tools.base import HasRepo, Tool, ToolParams, schema_field


class Scaffold(Tool):
    name = "scaffold"
    category = "meta"
    description = (
        "Generate sylvan/ project context directory and agent instructions. "
        "Creates auto-generated architecture docs, quality reports, dependency maps, "
        "and planning directories (future/working/completed). Also generates the "
        "agent instruction file (CLAUDE.md or .cursorrules) that teaches the agent "
        "how to use the sylvan/ directory. Run after indexing a project."
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
