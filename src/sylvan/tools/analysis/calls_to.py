"""MCP tool: calls_to."""

from sylvan.tools.base import HasSymbol, Tool, ToolParams, schema_field


class CallsTo(Tool):
    name = "what_does_this_call"
    category = "analysis"
    description = (
        "Returns all symbols that a given function or method calls. Each callee "
        "includes file path, signature, and line number. Shows what a function depends on."
    )

    class Params(HasSymbol, ToolParams):
        max_results: int = schema_field(
            default=50,
            ge=1,
            le=1000,
            description="Maximum results to return",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.analysis.structure.reference_graph import get_references_from
        from sylvan.tools.base.meta import get_meta

        refs = await get_references_from(p.symbol_id)
        refs = refs[: p.max_results]
        get_meta().results_count(len(refs))
        result = {
            "callees": refs,
            "symbol_id": p.symbol_id,
        }

        if refs:
            first = refs[0]
            sid = first.get("target_symbol_id")
            if sid:
                self.hints().next_symbol(sid).apply(result)

        return result
