"""MCP tool: suggest_queries -- intelligent query suggestions for exploring a repo."""

from sylvan.tools.base import HasRepo, Tool, ToolParams


class SuggestQueries(Tool):
    name = "suggest_queries"
    category = "meta"
    description = (
        "Not sure where to start? This suggests the best queries for exploring "
        "a repo -- key entry points, popular classes, unexplored areas, docs. "
        "Session-aware: adapts based on what you've already looked at."
    )

    class Params(HasRepo, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.meta import suggest_queries as _svc
        from sylvan.tools.base.meta import get_meta

        result = await _svc(p.repo)
        get_meta().extra("suggestion_count", len(result["suggestions"]))
        return {**result}


async def suggest_queries(repo: str, **_kwargs: object) -> dict:
    return await SuggestQueries().execute({"repo": repo})
