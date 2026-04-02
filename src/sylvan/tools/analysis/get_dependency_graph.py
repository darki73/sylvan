"""MCP tool: get_dependency_graph."""

from sylvan.tools.base import HasDirection, HasFilePath, HasRepo, Tool, ToolParams, schema_field


class GetDependencyGraph(Tool):
    name = "get_dependency_graph"
    category = "analysis"
    description = (
        "Build a file-level import dependency graph. Shows what a file imports "
        "(direction=imports), what imports it (direction=importers), or both. "
        "Returns nodes with symbol counts and directed edges. Use to understand "
        "module coupling before refactoring."
    )

    class Params(HasRepo, HasFilePath, HasDirection, ToolParams):
        depth: int = schema_field(
            default=1,
            ge=1,
            le=3,
            description="Import hops to follow (1-3)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().dependency_graph(p.repo, p.file_path, direction=p.direction, depth=p.depth)

        meta = get_meta()
        meta.extra("node_count", result.pop("node_count"))
        meta.extra("edge_count", result.pop("edge_count"))
        meta.extra("direction", result.pop("direction"))
        meta.extra("depth", result.pop("depth"))

        nodes = result.get("nodes", {})
        if nodes:
            best = max(nodes.items(), key=lambda kv: kv[1].get("symbol_count", 0))
            if not best[1].get("is_target"):
                self.hints().next_outline(p.repo, best[0]).apply(result)

        return result
