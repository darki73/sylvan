"""MCP tool: get_class_hierarchy."""

from sylvan.tools.base import HasOptionalRepo, Tool, ToolParams, schema_field


class GetClassHierarchy(Tool):
    name = "inheritance_chain"
    category = "analysis"
    description = (
        "Returns the inheritance chain for a class: ancestors (what it extends) "
        "and descendants (what extends it). Searched by class name across the index."
    )

    class Params(HasOptionalRepo, ToolParams):
        class_name: str = schema_field(description="Class name to analyze")

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().class_hierarchy(p.class_name, repo=p.repo)
        meta = get_meta()
        meta.extra("ancestors", len(result.get("ancestors", [])))
        meta.extra("descendants", len(result.get("descendants", [])))

        target = result.get("target", {})
        sid = target.get("symbol_id")
        if sid:
            self.hints().next_symbol(sid).apply(result)

        return result
