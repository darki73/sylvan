"""MCP tool: get_git_context."""

from sylvan.tools.base import HasOptionalFilePath, HasOptionalSymbol, HasRepo, Tool, ToolParams


class GetGitContext(Tool):
    name = "get_git_context"
    category = "analysis"
    description = (
        "Get git blame, change frequency, and recent commits for a file or symbol. "
        "Answers 'who last touched this?' and 'how often does this change?' "
        "without running git commands manually."
    )

    class Params(HasRepo, HasOptionalFilePath, HasOptionalSymbol, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.git import GitService

        result = await GitService().context(p.repo, file_path=p.file_path, symbol_id=p.symbol_id)

        blame = result.get("blame", [])
        file_path = result.get("file", "")
        if blame and file_path:
            first_entry = blame[0] if isinstance(blame, list) else None
            if first_entry and first_entry.get("line_start"):
                self.hints().read(
                    file_path, first_entry["line_start"], first_entry.get("line_end", first_entry["line_start"])
                ).apply(result)

        return result
