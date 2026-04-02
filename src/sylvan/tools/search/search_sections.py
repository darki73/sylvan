"""MCP tool: search_sections -- search indexed documentation sections."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import (
    HasDocPath,
    HasOptionalRepo,
    HasQuery,
    MeasureMethod,
    Tool,
    ToolParams,
    schema_field,
)
from sylvan.tools.base.meta import get_meta


class SearchSections(Tool):
    name = "search_sections"
    category = "search"
    description = (
        "PREFERRED over Read/Grep for finding documentation. Searches indexed "
        "doc sections (markdown, RST, HTML, OpenAPI, etc.) by title, summary, "
        "or tags. Returns section summaries without reading files. Use this to "
        "find configuration docs, API references, or any documentation section."
    )

    class Params(HasQuery, HasOptionalRepo, HasDocPath, ToolParams):
        max_results: int = schema_field(
            default=10,
            ge=1,
            le=1000,
            description="Maximum results to return",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.error_codes import SylvanError
        from sylvan.services.search import SearchService

        try:
            data = await SearchService().sections(
                p.query,
                repo=p.repo,
                doc_path=p.doc_path,
                max_results=p.max_results,
            )
        except SylvanError as exc:
            exc._meta = {}
            raise

        self._data = data

        result: dict[str, Any] = {"sections": data["sections"]}

        meta = get_meta()
        meta.results_count(data["results_count"])
        meta.query(data["query"])

        repo_id = data["repo_id"]
        if repo_id:
            meta.repo_id(repo_id)

        if result["sections"]:
            first = result["sections"][0]
            self.hints().next_tool("get_section", f"get_section(section_id='{first['section_id']}')").apply(result)

        return result

    def measure(self, result: dict) -> tuple[int, int]:
        data = getattr(self, "_data", None)
        if data is None:
            return 0, 0
        return data.get("returned_tokens", 0), data.get("equivalent_tokens", 0)

    def measure_method(self) -> str:
        return MeasureMethod.BYTE_ESTIMATE


async def search_sections(**kwargs: Any) -> dict:
    return await SearchSections().execute(kwargs)
