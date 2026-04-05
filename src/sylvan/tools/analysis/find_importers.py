"""MCP tools: find_importers, batch_find_importers."""

from sylvan.tools.base import (
    HasFilePath,
    HasFilePaths,
    HasRepo,
    Tool,
    ToolParams,
    schema_field,
)


class FindImporters(Tool):
    name = "who_depends_on_this"
    category = "analysis"
    description = (
        "Returns all files that import a given module. Each result includes "
        "has_importers flag: false means the import chain is transitively dead "
        "(nothing depends on that importer). Structural query based on the import "
        "graph, not text matching."
    )

    class Params(HasRepo, HasFilePath, ToolParams):
        max_results: int = schema_field(
            default=50,
            ge=1,
            le=1000,
            description="Maximum results to return",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        result = await AnalysisService().find_importers(p.repo, p.file_path, max_results=p.max_results)
        get_meta().results_count(len(result["importers"]))

        if result["importers"]:
            first = result["importers"][0]
            self.hints().next_outline(p.repo, first["path"]).apply(result)

        return result


class BatchFindImporters(Tool):
    name = "who_depends_on_these"
    category = "analysis"
    description = (
        "Importers for multiple files in one call. Returns dependency lists per file with per-file max_results limit."
    )

    class Params(HasRepo, HasFilePaths, ToolParams):
        max_results: int = schema_field(
            default=20,
            ge=1,
            le=100,
            description="Max importers per file (default: 20)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService
        from sylvan.tools.base.meta import get_meta

        data = await AnalysisService().batch_find_importers(p.repo, p.file_paths, max_results=p.max_results)
        result = {"results": data["results"], "not_found": data["not_found"]}
        meta = get_meta()
        meta.found(data["found"])
        meta.not_found_count(len(data["not_found"]))
        meta.extra("total_importers", data["total_importers"])
        return result
