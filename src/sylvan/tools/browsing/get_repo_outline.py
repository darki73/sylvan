"""MCP tool: get_repo_outline -- high-level summary of an indexed repo."""

from __future__ import annotations

from sylvan.tools.base import (
    HasRepo,
    Tool,
    ToolParams,
)


class GetRepoOutline(Tool):
    name = "get_repo_outline"
    category = "retrieval"
    description = (
        "START HERE when exploring an unfamiliar repo. Returns a high-level "
        "summary: file count, languages, symbol breakdown by kind, documentation "
        "coverage. Use this to orient before diving into search_symbols or get_toc."
    )

    class Params(HasRepo, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.symbol import SymbolService
        from sylvan.tools.base.meta import get_meta
        from sylvan.tools.support.response import check_staleness

        result = await SymbolService().repo_outline(p.repo)

        repo_id = result.pop("repo_id")

        get_meta().repo(p.repo)
        await check_staleness(repo_id, result)
        return result
