"""MCP tool: get_related."""

from sylvan.tools.base import HasSymbol, Tool, ToolParams, schema_field


class GetRelated(Tool):
    name = "get_related"
    category = "analysis"
    description = (
        "Find symbols related to a given symbol -- by co-location, shared imports, "
        "or name similarity. Useful for discovering related code to understand context."
    )

    class Params(HasSymbol, ToolParams):
        max_results: int = schema_field(
            default=10,
            ge=1,
            le=100,
            description="Maximum results to return",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().related(p.symbol_id, max_results=p.max_results)
        get_meta().results_count(len(result["related"]))

        if result["related"]:
            first = result["related"][0]
            self.hints().next_symbol(first["symbol_id"]).apply(result)

        return result
