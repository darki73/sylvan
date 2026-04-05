"""MCP tool: get_recent_changes."""

from sylvan.tools.base import HasOptionalFilePath, HasRepo, Tool, ToolParams, schema_field


class GetRecentChanges(Tool):
    name = "whats_changed_recently"
    category = "analysis"
    description = (
        "Returns files changed in the last N commits with language, symbol count, "
        "and last commit message per file. Lighter than what_changed_in_symbols "
        "when you only need file-level change overview."
    )

    class Params(HasRepo, HasOptionalFilePath, ToolParams):
        commits: int = schema_field(
            default=5,
            ge=1,
            le=100,
            description="Number of commits to look back (default: 5)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.git import GitService
        from sylvan.tools.base.meta import get_meta

        result = await GitService().recent_changes(p.repo, commits=p.commits, file_path=p.file_path)

        if "error" in result:
            return result

        meta = get_meta()
        meta.extra("commits_back", result["commits"])
        meta.extra("files_changed", len(result["files_changed"]))

        if result["files_changed"]:
            first = result["files_changed"][0]
            self.hints().next_outline(p.repo, first["file"]).apply(result)

        return result
