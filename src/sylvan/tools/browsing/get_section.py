"""MCP tools: get_section, get_sections -- retrieve documentation sections."""

from __future__ import annotations

from sylvan.tools.base import (
    HasSectionId,
    HasSectionIds,
    HasVerify,
    MeasureMethod,
    SectionPresenter,
    Tool,
    ToolParams,
)
from sylvan.tools.base.meta import get_meta


class GetSection(Tool):
    name = "get_section"
    category = "retrieval"
    description = (
        "PREFERRED over Read for viewing documentation. Retrieves the exact "
        "content of a doc section by ID -- one heading's worth of content instead "
        "of the entire file. Use section IDs from search_sections or get_toc."
    )

    class Params(HasSectionId, HasVerify, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.section import SectionService
        from sylvan.tools.support.response import check_staleness
        from sylvan.tools.support.token_counting import count_tokens

        svc = SectionService().with_content()
        if p.verify:
            svc = svc.verified()

        sec = await svc.find(p.section_id)

        doc_path = await sec._model._resolve_file_path()
        result = SectionPresenter.full(sec._model, content=sec.content, doc_path=doc_path)
        result["repo"] = await sec._model._resolve_repo_name()
        result["references"] = sec._model.references or []

        self._returned_tokens = 0
        self._equivalent_tokens = 0
        if sec.content and sec.file_record:
            file_content = await sec.file_record.get_content()
            returned = count_tokens(sec.content)
            if returned is not None and file_content:
                file_text = file_content.decode("utf-8", errors="replace")
                equivalent = count_tokens(file_text)
                if equivalent and returned > 0 and equivalent > 0:
                    self._returned_tokens = returned
                    self._equivalent_tokens = equivalent

        repo_name = await sec._model._resolve_repo_name()
        file_path = result.get("doc_path", "")
        if file_path:
            hints = self.hints()
            if repo_name:
                hints.next_tool("toc", f"get_toc(repo='{repo_name}', doc_path='{file_path}')")
                hints.next_importers(repo_name, file_path)
            hints.working_files_from_session()
            hints.apply(result)

        if sec.file_record:
            await check_staleness(sec.file_record.repo_id, result)

        return result

    def measure(self, result: dict) -> tuple[int, int]:
        return getattr(self, "_returned_tokens", 0), getattr(self, "_equivalent_tokens", 0)

    def measure_method(self) -> str:
        return MeasureMethod.TIKTOKEN_CL100K


class GetSections(Tool):
    name = "get_sections"
    category = "retrieval"
    description = "Batch retrieve multiple doc sections at once. More efficient than multiple get_section calls."

    class Params(HasSectionIds, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.section import SectionService
        from sylvan.tools.support.response import check_staleness

        svc = SectionService().with_content()
        found_results = await svc.find_many(p.section_ids)

        found_ids = {r.section_id for r in found_results}
        not_found = [sid for sid in p.section_ids if sid not in found_ids]
        repo_ids: set[int] = set()

        sections = []
        for r in found_results:
            if r.file_record:
                repo_ids.add(r.file_record.repo_id)
            file_path = await r._model._resolve_file_path()
            sections.append(
                {
                    "section_id": r.section_id,
                    "title": r.title,
                    "level": r.level,
                    "doc_path": file_path,
                    "content": r.content,
                }
            )

        meta = get_meta()
        meta.found(len(sections))
        meta.not_found_count(len(not_found))

        result = {
            "sections": sections,
            "not_found": not_found,
        }

        for rid in repo_ids:
            await check_staleness(rid, result)

        return result
