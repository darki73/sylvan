"""MCP tool: search_text -- full-text search across file content."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import (
    HasContextLines,
    HasFileFilter,
    HasOptionalRepo,
    HasPagination,
    HasQuery,
    MeasureMethod,
    Tool,
    ToolParams,
)
from sylvan.tools.base.meta import get_meta


class SearchText(Tool):
    name = "find_text"
    category = "search"
    description = (
        "Full-text search across indexed file content. Finds comments, strings, "
        "TODOs, and literal text that symbol search misses. Returns matching "
        "lines with optional surrounding context."
    )

    class Params(HasQuery, HasOptionalRepo, HasFileFilter, HasPagination, HasContextLines, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.search import SearchService

        data = await SearchService().text(
            p.query,
            repo=p.repo,
            file_pattern=p.file_pattern,
            max_results=p.max_results,
            context_lines=p.context_lines,
        )

        self._data = data

        result: dict[str, Any] = {"matches": data["matches"]}

        meta = get_meta()
        meta.results_count(data["results_count"])
        meta.query(data["query"])

        repo_id = data["repo_id"]
        if repo_id:
            meta.repo_id(repo_id)

        if result["matches"]:
            first = result["matches"][0]
            self.hints().read(first["file_path"], first["line"], first["line"]).apply(result)

        return result

    def measure(self, result: dict) -> tuple[int, int]:
        data = getattr(self, "_data", None)
        if data is None:
            return 0, 0
        return data.get("returned_tokens", 0), data.get("equivalent_tokens", 0)

    def measure_method(self) -> str:
        return MeasureMethod.BYTE_ESTIMATE


async def search_text(**kwargs: Any) -> dict:
    return await SearchText().execute(kwargs)
