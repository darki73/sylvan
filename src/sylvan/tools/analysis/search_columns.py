"""MCP tool: search_columns."""

from sylvan.tools.base import HasQuery, HasRepo, Tool, ToolParams, schema_field


class SearchColumns(Tool):
    name = "find_columns"
    category = "analysis"
    description = (
        "Searches column metadata from ecosystem context providers (dbt). "
        "Finds columns by name or description across models. "
        "Filterable by model name pattern."
    )

    class Params(HasRepo, HasQuery, ToolParams):
        model_pattern: str | None = schema_field(
            default=None,
            description="Glob pattern to filter model names",
        )
        max_results: int = schema_field(
            default=20,
            ge=1,
            le=200,
            description="Maximum results to return",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().search_columns(
            p.repo, p.query, model_pattern=p.model_pattern, max_results=p.max_results
        )

        meta = get_meta()
        if "count" in result:
            meta.results_count(result.pop("count"))
        if "providers_found" in result:
            meta.extra("providers_found", result.pop("providers_found"))
        if "providers" in result:
            meta.extra("providers", result.pop("providers"))

        return result
