"""MCP tools: get_symbol, get_symbols -- retrieve symbol source code."""

from __future__ import annotations

from sylvan.tools.base import (
    HasContextLines,
    HasOptionalRepo,
    HasSymbol,
    HasSymbolIds,
    HasVerify,
    MeasureMethod,
    Tool,
    ToolParams,
)
from sylvan.tools.base.meta import get_meta


class GetSymbol(Tool):
    name = "read_symbol"
    category = "retrieval"
    description = (
        "Retrieves exact source code of a function, class, or method by symbol ID. "
        "Returns only that symbol's lines, signature, and docstring. "
        "~50-200 tokens vs ~2000 for reading the full file."
    )

    class Params(HasSymbol, HasOptionalRepo, HasVerify, HasContextLines, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.symbol import SymbolService
        from sylvan.tools.support.response import check_staleness
        from sylvan.tools.support.token_counting import count_tokens

        svc = SymbolService().with_source().with_file()
        if p.verify:
            svc = svc.verified()
        if p.context_lines > 0:
            svc = svc.with_context_lines(p.context_lines)

        sym = await svc.find(p.symbol_id, repo=p.repo)

        result = await sym._model.to_detail_dict()
        if sym.context_lines and sym.context_lines > 0:
            result["source"] = sym.source
            result["context_lines"] = sym.context_lines

        if sym.hash_verified is not None:
            result["hash_verified"] = sym.hash_verified
            if sym.drift_warning:
                result["drift_warning"] = sym.drift_warning

        self._returned_tokens = 0
        self._equivalent_tokens = 0
        if sym.source and sym.file_record:
            file_content = await sym.file_record.get_content()
            returned = count_tokens(sym.source)
            if returned is not None and file_content:
                file_text = file_content.decode("utf-8", errors="replace")
                equivalent = count_tokens(file_text)
                if equivalent and returned > 0 and equivalent > 0:
                    self._returned_tokens = returned
                    self._equivalent_tokens = equivalent

        repo_name = await sym._model._resolve_repo_name()
        self.hints().for_symbol(
            symbol_id=result.get("symbol_id", ""),
            file_path=result.get("file", ""),
            line_start=result.get("line_start"),
            line_end=result.get("line_end"),
            repo=repo_name or None,
        ).apply(result)

        if sym.file_record:
            await check_staleness(sym.file_record.repo_id, result)

        return result

    def measure(self, result: dict) -> tuple[int, int]:
        return getattr(self, "_returned_tokens", 0), getattr(self, "_equivalent_tokens", 0)

    def measure_method(self) -> str:
        return MeasureMethod.TIKTOKEN_CL100K


class GetSymbols(Tool):
    name = "read_symbols"
    category = "retrieval"
    description = (
        "Batch retrieves source code for multiple symbols in one call. "
        "Returns source, signature, and file info for each. Reports not_found for any missing IDs."
    )

    class Params(HasSymbolIds, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.symbol import SymbolService
        from sylvan.tools.support.response import check_staleness

        svc = SymbolService().with_source().with_file()
        found_results = await svc.find_many(p.symbol_ids)

        found_ids = {r.symbol_id for r in found_results}
        not_found = [sid for sid in p.symbol_ids if sid not in found_ids]
        repo_ids: set[int] = set()

        symbols = []
        for r in found_results:
            if r.file_record:
                repo_ids.add(r.file_record.repo_id)
            file_path = await r._model._resolve_file_path()
            symbols.append(
                {
                    "symbol_id": r.symbol_id,
                    "name": r.name,
                    "kind": r.kind,
                    "language": r.language,
                    "file": file_path,
                    "signature": r.signature or "",
                    "source": r.source or "",
                }
            )

        meta = get_meta()
        meta.found(len(symbols))
        meta.not_found_count(len(not_found))

        result = {
            "symbols": symbols,
            "not_found": not_found,
        }

        for rid in repo_ids:
            await check_staleness(rid, result)

        return result
