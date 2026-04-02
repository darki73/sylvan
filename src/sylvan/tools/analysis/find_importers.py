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
    name = "find_importers"
    category = "analysis"
    description = (
        "Find all files that import a given file. Answers 'who depends on this "
        "module?' -- a structural query that Grep cannot reliably answer. Each "
        "importer includes has_importers: when false, the importer has no importers "
        "itself -- meaning the import chain is transitively dead."
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
    name = "batch_find_importers"
    category = "analysis"
    description = (
        "Find importers for MULTIPLE files in ONE call. More efficient than "
        "calling find_importers repeatedly. Use to check dependency status "
        "of several modules at once."
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
