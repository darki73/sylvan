"""MCP tool: get_repo_briefing -- structured repo orientation."""

from __future__ import annotations

from sylvan.tools.base import (
    HasRepo,
    Tool,
    ToolParams,
)


class GetRepoBriefing(Tool):
    name = "repo_deep_dive"
    category = "retrieval"
    description = (
        "Full repository orientation: stats (files, symbols, sections), directory "
        "tree, language breakdown, and manifest contents (pyproject.toml, "
        "package.json, go.mod). Replaces 5-10 separate calls to understand "
        "a repo's scale, structure, and stack."
    )

    class Params(HasRepo, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.briefing import BriefingService
        from sylvan.tools.base.meta import get_meta
        from sylvan.tools.support.response import check_staleness

        result = await BriefingService().get(p.repo)

        repo_id = result.pop("repo_id")

        get_meta().repo(p.repo)
        await check_staleness(repo_id, result)
        return result
