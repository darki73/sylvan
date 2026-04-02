"""MCP tools: get_toc, get_toc_tree -- documentation table of contents."""

from __future__ import annotations

from sylvan.tools.base import (
    HasDocPath,
    HasMaxDepth,
    HasRepo,
    Tool,
    ToolParams,
)


class GetToc(Tool):
    name = "get_toc"
    category = "retrieval"
    description = (
        "PREFERRED over Read for browsing documentation. Returns a structured "
        "table of contents for all indexed docs -- every heading, section, and "
        "their hierarchy. Use this to navigate docs instead of reading files."
    )

    class Params(HasRepo, HasDocPath, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.database.orm import Repo
        from sylvan.services.section import SectionService
        from sylvan.tools.base.meta import get_meta
        from sylvan.tools.support.response import check_staleness

        data = await SectionService().toc(p.repo, doc_path=p.doc_path)
        data.pop("repo_name")

        get_meta().extra("section_count", data.pop("section_count"))
        result = {**data}

        repo_obj = await Repo.where(name=p.repo).first()
        if repo_obj:
            await check_staleness(repo_obj.id, result)

        toc = result.get("toc", [])
        if toc:
            first = toc[0]
            self.hints().next_tool("get_section", f"get_section(section_id='{first['section_id']}')").apply(result)

        return result


class GetTocTree(Tool):
    name = "get_toc_tree"
    category = "retrieval"
    description = (
        "Nested tree table of contents grouped by document. Richer than get_toc "
        "for multi-doc repos. Use max_depth to limit heading levels and reduce output size."
    )

    class Params(HasRepo, HasMaxDepth, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.database.orm import Repo
        from sylvan.services.section import SectionService
        from sylvan.tools.base.meta import get_meta
        from sylvan.tools.support.response import check_staleness

        data = await SectionService().toc_tree(p.repo, max_depth=p.max_depth)
        data.pop("repo_name")

        meta = get_meta()
        meta.extra("document_count", data.pop("document_count"))
        meta.extra("section_count", data.pop("section_count"))
        truncated = data.pop("truncated_sections", None)
        depth = data.pop("max_depth", None)
        if truncated:
            meta.extra("truncated_sections", truncated)
            meta.extra("max_depth", depth)

        result = {**data}

        repo_obj = await Repo.where(name=p.repo).first()
        if repo_obj:
            await check_staleness(repo_obj.id, result)

        return result
