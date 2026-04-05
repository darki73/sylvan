"""MCP tool: get_quality."""

from sylvan.tools.base import HasRepo, Tool, ToolParams, schema_field


class GetQuality(Tool):
    name = "find_tech_debt"
    category = "analysis"
    description = (
        "Returns quality metrics per symbol: has_tests, has_docs, has_types, "
        "complexity score. Filterable by untested_only, undocumented_only, "
        "or min_complexity threshold."
    )

    class Params(HasRepo, ToolParams):
        untested_only: bool = schema_field(default=False, description="Only show untested symbols")
        undocumented_only: bool = schema_field(default=False, description="Only show undocumented symbols")
        min_complexity: int = schema_field(default=0, ge=0, description="Minimum cyclomatic complexity threshold")
        limit: int = schema_field(default=50, ge=1, le=1000, description="Maximum results to return")

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().quality(
            p.repo,
            untested_only=p.untested_only,
            undocumented_only=p.undocumented_only,
            min_complexity=p.min_complexity,
            limit=p.limit,
        )
        get_meta().results_count(len(result["symbols"]))

        if result["symbols"]:
            worst = result["symbols"][0]
            self.hints().next_symbol(worst["symbol_id"]).apply(result)

        return result
