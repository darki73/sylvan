"""MCP tool: search_similar_symbols -- vector similarity search from a source symbol."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import (
    HasOptionalRepo,
    HasSymbol,
    MeasureMethod,
    Tool,
    ToolParams,
    schema_field,
)
from sylvan.tools.base.meta import get_meta


class SearchSimilarSymbols(Tool):
    name = "find_similar_code"
    category = "search"
    description = (
        "Vector similarity search for code patterns. Given a symbol ID, finds "
        "semantically similar functions, classes, or methods across the codebase. "
        "Useful for discovering alternative implementations or repeated patterns."
    )

    class Params(HasSymbol, HasOptionalRepo, ToolParams):
        max_results: int = schema_field(
            default=10,
            ge=1,
            le=1000,
            description="Maximum similar symbols to return (default: 10)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.error_codes import SylvanError
        from sylvan.services.search import SearchService

        try:
            data = await SearchService().similar(
                p.symbol_id,
                repo=p.repo,
                max_results=p.max_results,
            )
        except SylvanError as exc:
            exc._meta = {}
            raise

        self._data = data

        result: dict[str, Any] = {
            "source": data["source"],
            "similar": data["similar"],
        }

        meta = get_meta()
        meta.results_count(data["results_count"])
        meta.extra("source_symbol", data["source_symbol"])

        repo_id = data["repo_id"]
        if repo_id:
            meta.repo_id(repo_id)

        if result["similar"]:
            first = result["similar"][0]
            self.hints().next_symbol(first["symbol_id"]).apply(result)

        return result

    def measure(self, result: dict) -> tuple[int, int]:
        data = getattr(self, "_data", None)
        if data is None:
            return 0, 0
        return data.get("returned_tokens", 0), data.get("equivalent_tokens", 0)

    def measure_method(self) -> str:
        return MeasureMethod.BYTE_ESTIMATE


async def search_similar_symbols(**kwargs: Any) -> dict:
    return await SearchSimilarSymbols().execute(kwargs)
