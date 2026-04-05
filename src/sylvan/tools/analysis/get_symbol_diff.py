"""MCP tool: get_symbol_diff."""

from sylvan.tools.base import HasOptionalFilePath, HasRepo, Tool, ToolParams, schema_field


class GetSymbolDiff(Tool):
    name = "what_changed_in_symbols"
    category = "analysis"
    description = (
        "Compares symbols between the current index and a previous git commit. "
        "Returns symbols added, removed, or changed with signature diffs. "
        "Works at symbol level, not line level."
    )

    class Params(HasRepo, HasOptionalFilePath, ToolParams):
        commit: str = schema_field(
            default="HEAD~1",
            description="Git ref to compare against (default: HEAD~1)",
        )
        max_files: int = schema_field(
            default=50,
            ge=1,
            le=200,
            description="Maximum number of files to diff",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.git import GitService
        from sylvan.tools.base.meta import get_meta

        result = await GitService().symbol_diff(p.repo, commit=p.commit, file_path=p.file_path, max_files=p.max_files)

        if "error" in result:
            return result

        meta = get_meta()
        meta.extra("files_compared", result.pop("files_compared"))
        meta.extra("files_with_changes", result.pop("files_with_changes"))
        meta.extra("commit", p.commit)

        file_diffs = result.get("file_diffs", [])
        if file_diffs:
            first_diff = file_diffs[0]
            changed = first_diff.get("changed", []) or first_diff.get("added", [])
            if changed:
                sym_name = changed[0].get("qualified_name", "")
                if sym_name:
                    self.hints().next_tool(
                        "get_source",
                        f"find_code(query='{sym_name}', repo='{result.get('repo', '')}')",
                    ).apply(result)

        return result
