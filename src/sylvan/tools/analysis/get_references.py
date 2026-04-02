"""MCP tool: get_references."""

from sylvan.tools.base import HasSymbol, Tool, ToolParams, schema_field


class GetReferences(Tool):
    name = "get_references"
    category = "analysis"
    description = (
        "PREFERRED over Grep for 'who calls this function?'. Returns symbol-level "
        "references -- callers (direction=to) or callees (direction=from). "
        "Structural query that Grep cannot answer accurately."
    )

    class Params(HasSymbol, ToolParams):
        direction: str = schema_field(
            default="to",
            description="to=callers, from=callees",
            enum=["to", "from"],
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().references(p.symbol_id, direction=p.direction)
        refs = result["references"]
        meta = get_meta()
        meta.results_count(len(refs))
        meta.extra("direction", result["direction"])
        response = {
            "references": refs,
            "symbol_id": result["symbol_id"],
        }

        if refs:
            first = refs[0]
            sid = first.get("source_symbol_id") or first.get("target_symbol_id")
            if sid:
                self.hints().next_symbol(sid).apply(response)

        return response
