"""MCP tool: get_file_tree -- compact directory tree for a repo."""

from __future__ import annotations

from sylvan.tools.base import (
    HasMaxDepth,
    HasRepo,
    Tool,
    ToolParams,
)


class GetFileTree(Tool):
    name = "get_file_tree"
    category = "retrieval"
    description = (
        "PREFERRED over ls/Glob for exploring repo structure. Returns a compact "
        "indented tree (like the `tree` command) with language and symbol counts. "
        "Directories beyond max_depth are collapsed with file counts. "
        "Use this instead of running ls or Glob to understand a project layout."
    )

    class Params(HasRepo, HasMaxDepth, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.symbol import SymbolService
        from sylvan.tools.base.meta import get_meta
        from sylvan.tools.support.response import check_staleness

        data = await SymbolService().file_tree(p.repo, max_depth=p.max_depth)

        repo_id = data.pop("repo_id")
        truncated = data.pop("truncated")

        meta = get_meta()
        meta.repo(p.repo)
        meta.extra("files", data.pop("files"))
        meta.extra("max_depth", data.pop("max_depth"))
        if truncated:
            meta.extra("truncated", True)

        result = {**data}
        await check_staleness(repo_id, result)

        from sylvan.database.orm import FileRecord, Repo

        repo_obj = await Repo.where(name=p.repo).first()
        if repo_obj:
            first_file = await FileRecord.where(repo_id=repo_obj.id).where_not_null("language").order_by("path").first()
            if first_file:
                self.hints().next_outline(p.repo, first_file.path).apply(result)

        return result
