"""MCP tool: rename_symbol."""

from sylvan.tools.base import HasSymbol, Tool, ToolParams, schema_field


class RenameSymbol(Tool):
    name = "rename_everywhere"
    category = "analysis"
    description = (
        "Finds all edit locations needed to rename a symbol. Returns exact file, "
        "line, old_text, and new_text for each occurrence. Uses blast radius to "
        "find affected files across the import graph."
    )

    class Params(HasSymbol, ToolParams):
        new_name: str = schema_field(
            description="Desired new name (must be a valid identifier)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().rename_symbol(p.symbol_id, p.new_name)

        if "error" in result:
            return result

        meta = get_meta()
        meta.extra("affected_files", result.pop("affected_files"))
        meta.extra("total_edits", result.pop("total_edits"))
        meta.extra("old_name", result["symbol"]["name"])
        meta.extra("new_name", result["new_name"])

        edits = result.get("edits", [])
        if edits:
            affected_files = {e["file"] for e in edits}
            hints = self.hints()
            for fp in list(affected_files)[:5]:
                hints.reindex("", fp)
            test_files = [fp for fp in affected_files if "test" in fp.lower()]
            if test_files:
                hints.test_files(test_files)
            hints.apply(result)

        return result
