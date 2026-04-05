"""MCP tools: get_blast_radius, batch_blast_radius."""

from sylvan.tools.base import HasSymbol, HasSymbolIds, Tool, ToolParams, schema_field


class GetBlastRadius(Tool):
    name = "what_breaks_if_i_change"
    category = "analysis"
    description = (
        "Shows which files and symbols would be affected by changing a given symbol. "
        "Separates confirmed impact (name actually referenced) from potential impact "
        "(file imported but name not confirmed). Follows import chains up to 3 hops."
    )

    class Params(HasSymbol, ToolParams):
        depth: int = schema_field(
            default=2,
            ge=1,
            le=3,
            description="Import hops to follow (1-3)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().blast_radius(p.symbol_id, depth=p.depth)
        meta = get_meta()
        meta.extra("confirmed_count", len(result.get("confirmed", [])))
        meta.extra("potential_count", len(result.get("potential", [])))

        confirmed = result.get("confirmed", [])
        if confirmed:
            hints = self.hints()
            for entry in confirmed[:3]:
                syms = entry.get("symbols", [])
                if syms and syms[0].get("line_start"):
                    hints.read(entry["file"], syms[0]["line_start"], syms[0].get("line_end", syms[0]["line_start"]))
            hints.apply(result)

        return result


class BatchBlastRadius(Tool):
    name = "what_breaks_if_i_change_these"
    category = "analysis"
    description = (
        "Blast radius for multiple symbols in one call. Returns confirmed "
        "and potential impact for each symbol independently."
    )

    class Params(HasSymbolIds, ToolParams):
        depth: int = schema_field(
            default=2,
            ge=1,
            le=3,
            description="Import hops to follow (1-3)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        data = await AnalysisService().batch_blast_radius(p.symbol_ids, depth=p.depth)
        result = {"results": data["results"]}
        meta = get_meta()
        meta.extra("symbols_analysed", data["symbols_analysed"])
        meta.extra("total_affected", data["total_affected"])
        return result
