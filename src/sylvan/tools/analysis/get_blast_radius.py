"""MCP tools: get_blast_radius, batch_blast_radius."""

from sylvan.tools.base import HasSymbol, HasSymbolIds, Tool, ToolParams, schema_field


class GetBlastRadius(Tool):
    name = "get_blast_radius"
    category = "analysis"
    description = (
        "BEFORE making changes, check the blast radius. Shows which files and "
        "symbols would be affected by changing a symbol -- with confirmed (name "
        "referenced) vs potential (file imported) impact. Grep cannot answer this."
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
    name = "batch_blast_radius"
    category = "analysis"
    description = (
        "Check blast radius for MULTIPLE symbols in ONE call. More efficient "
        "than calling get_blast_radius repeatedly before a large refactor. "
        "Returns confirmed and potential impact for each symbol."
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
