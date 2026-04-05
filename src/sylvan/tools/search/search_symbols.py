"""MCP tools: search_symbols and batch_search_symbols."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import (
    HasFileFilter,
    HasKindFilter,
    HasLanguageFilter,
    HasOptionalRepo,
    HasPagination,
    HasQuery,
    MeasureMethod,
    Tool,
    ToolParams,
    schema_field,
)
from sylvan.tools.base.meta import get_meta


class SearchSymbols(Tool):
    name = "find_code"
    category = "search"
    description = (
        "Searches indexed symbols (functions, classes, methods, constants, types) "
        "by name, keyword, or docstring. Returns ranked results with signatures "
        "and locations, no file content loaded. Also searches indexed third-party "
        "libraries. ~50 tokens per result vs ~2000 for reading each file."
    )

    class Params(HasQuery, HasOptionalRepo, HasKindFilter, HasLanguageFilter, HasFileFilter, HasPagination, ToolParams):
        token_budget: int | None = schema_field(
            default=None,
            description=(
                "Optional token budget -- greedy-pack results until budget is "
                "exhausted. Reports tokens_used and tokens_remaining in _meta."
            ),
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.error_codes import SylvanError
        from sylvan.services.search import SearchService

        svc = SearchService().with_session_reranking()
        if p.token_budget is not None and p.token_budget > 0:
            svc = svc.with_token_budget(p.token_budget)

        try:
            data = await svc.symbols(
                p.query,
                repo=p.repo,
                kind=p.kind,
                language=p.language,
                file_pattern=p.file_pattern,
                max_results=p.max_results,
            )
        except SylvanError as exc:
            exc._meta = {}
            raise

        self._data = data

        result: dict[str, Any] = {"symbols": data["symbols"]}

        meta = get_meta()
        meta.results_count(data["results_count"])
        meta.query(data["query"])
        meta.already_seen(data["already_seen_deprioritized"])

        if data["token_budget"] is not None and data["token_budget"] > 0:
            meta.extra("tokens_used", data["tokens_used"])
            meta.extra("tokens_remaining", max(0, data["token_budget"] - data["tokens_used"]))

        repo_id = data["repo_id"]
        if repo_id:
            meta.repo_id(repo_id)

        if repo_id:
            from sylvan.tools.support.response import check_staleness

            await check_staleness(repo_id, result)

        if result["symbols"]:
            first = result["symbols"][0]
            self.hints().next_symbol(first["symbol_id"]).apply(result)

        return result

    def measure(self, result: dict) -> tuple[int, int]:
        data = getattr(self, "_data", None)
        if data is None:
            return 0, 0
        return data.get("returned_tokens", 0), data.get("equivalent_tokens", 0)

    def measure_method(self) -> str:
        return MeasureMethod.BYTE_ESTIMATE


class BatchSearchSymbols(Tool):
    name = "find_code_batch"
    category = "search"
    description = (
        "Multiple symbol searches in one call. Each query runs independently "
        "with optional repo, kind, and language overrides. Returns results grouped by query."
    )

    class Params(HasOptionalRepo, ToolParams):
        queries: list[dict] = schema_field(
            description="List of search queries to run",
        )
        max_results_per_query: int = schema_field(
            default=10,
            description="Default max results per query (default: 10)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.search import SearchService

        data = await SearchService().batch_symbols(
            p.queries,
            repo=p.repo,
            max_results_per_query=p.max_results_per_query,
        )

        self._data = data

        meta = get_meta()
        meta.extra("queries", data["queries_count"])
        meta.results_count(data["total_results"])

        return {"results": data["results"]}

    def measure(self, result: dict) -> tuple[int, int]:
        data = getattr(self, "_data", None)
        if data is None:
            return 0, 0
        return data.get("returned_tokens", 0), data.get("equivalent_tokens", 0)

    def measure_method(self) -> str:
        return MeasureMethod.BYTE_ESTIMATE


async def search_symbols(**kwargs: Any) -> dict:
    return await SearchSymbols().execute(kwargs)


async def batch_search_symbols(**kwargs: Any) -> dict:
    return await BatchSearchSymbols().execute(kwargs)
