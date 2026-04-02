"""MCP tool: get_recent_changes."""

from sylvan.tools.base import HasOptionalFilePath, HasRepo, Tool, ToolParams, schema_field


class GetRecentChanges(Tool):
    name = "get_recent_changes"
    category = "analysis"
    description = (
        "Show what changed in the last N commits at the file level. For each "
        "changed file in the index, shows language, symbol count, and last commit "
        "message. A lighter alternative to get_symbol_diff when you just need an "
        "overview of recent activity."
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
