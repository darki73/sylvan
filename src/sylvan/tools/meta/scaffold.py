"""MCP tool: scaffold -- generate sylvan/ directory and agent instructions."""

from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


@log_tool_call
async def scaffold(
    repo: str,
    agent: str = "claude",
    root: str | None = None,
) -> dict:
    """Generate the sylvan/ project context directory and agent instructions.

    Creates a structured directory in the project root with auto-generated
    documentation, architecture maps, quality reports, and planning
    directories.  Also generates the agent instruction file (CLAUDE.md,
    .cursorrules, etc.) that references sylvan/ for deep context.

    Args:
        repo: Indexed repo name.
        agent: Agent format (``"claude"``, ``"cursor"``, ``"copilot"``, ``"generic"``).
        root: Override project root path.

    Returns:
        Tool response dict with scaffold status and ``_meta`` envelope.
    """
    meta = MetaBuilder()

    from pathlib import Path

    from sylvan.scaffold.generator import async_scaffold_project

    result = await async_scaffold_project(
        repo,
        agent=agent,
        project_root=Path(root) if root else None,
    )

    meta.set("status", result.get("status", "error"))
    meta.set("files_created", result.get("files_created", 0))
    return wrap_response(result, meta.build())
