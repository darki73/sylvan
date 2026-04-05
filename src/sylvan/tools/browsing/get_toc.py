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
    name = "doc_table_of_contents"
    category = "retrieval"
    description = (
        "Returns a structured table of contents for indexed documentation. "
        "Lists every heading with section IDs and hierarchy. "
        "Filterable by document path."
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
            self.hints().next_tool("read_doc_section", f"read_doc_section(section_id='{first['section_id']}')").apply(
                result
            )

        return result


class GetTocTree(Tool):
    name = "doc_tree"
    category = "retrieval"
    description = (
        "Nested table of contents grouped by document. Returns heading trees "
        "per doc file with depth control. Better than doc_table_of_contents "
        "for repos with many documentation files."
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
