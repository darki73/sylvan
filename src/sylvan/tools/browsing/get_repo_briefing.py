"""MCP tool: get_repo_briefing -- structured repo orientation."""

from __future__ import annotations

from sylvan.tools.base import (
    HasRepo,
    Tool,
    ToolParams,
)


class GetRepoBriefing(Tool):
    name = "get_repo_briefing"
    category = "retrieval"
    description = (
        "Structured orientation for a repository - stats (files, symbols, "
        "sections), directory tree with per-directory file counts, language "
        "breakdown, and raw manifest contents (pyproject.toml, package.json, "
        "go.mod, etc). One call replaces the typical 5-10 orientation calls. "
        "Use this FIRST on unfamiliar repos to understand scale, structure, "
        "and stack before diving into search_symbols."
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
