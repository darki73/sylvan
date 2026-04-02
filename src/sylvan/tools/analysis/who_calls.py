"""MCP tool: who_calls."""

from sylvan.tools.base import HasSymbol, Tool, ToolParams, schema_field


class WhoCalls(Tool):
    name = "who_calls"
    category = "analysis"
    description = (
        "Find all symbols that call a given function or method. Returns callers "
        "with file paths, signatures, and line numbers. Use before changing a "
        "function to see exactly what breaks. More precise than find_importers "
        "which works at file level."
    )

    class Params(HasSymbol, ToolParams):
        max_results: int = schema_field(
            default=50,
            ge=1,
            le=1000,
            description="Maximum results to return",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.analysis.structure.reference_graph import get_references_to
        from sylvan.tools.base.meta import get_meta

        refs = await get_references_to(p.symbol_id)
        refs = refs[: p.max_results]
        get_meta().results_count(len(refs))
        result = {
            "callers": refs,
            "symbol_id": p.symbol_id,
        }

        if refs:
            first = refs[0]
            sid = first.get("source_symbol_id")
            if sid:
                self.hints().next_symbol(sid).apply(result)

        return result
