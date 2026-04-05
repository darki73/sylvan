"""MCP tool: get_context_bundle -- symbol + imports + callers in one call."""

from __future__ import annotations

import json

from sylvan.tools.base import (
    HasSymbol,
    MeasureMethod,
    Tool,
    ToolParams,
    schema_field,
)
from sylvan.tools.base.meta import get_meta
from sylvan.tools.base.presenters import FilePresenter, ImportPresenter, SymbolPresenter


class GetContextBundle(Tool):
    name = "understand_symbol"
    category = "retrieval"
    description = (
        "Returns a symbol's source code, file imports, callers, and sibling symbols "
        "in one call. Replaces 3-5 separate lookups when you need full context "
        "around a function or class."
    )

    class Params(HasSymbol, ToolParams):
        include_callers: bool = schema_field(
            default=False,
            description="Include files that reference this symbol",
        )
        include_imports: bool = schema_field(
            default=True,
            description="Include import statements from the symbol's file",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.context import get_context
        from sylvan.database.orm import FileImport, FileRecord, Symbol
        from sylvan.error_codes import SymbolNotFoundError
        from sylvan.tools.support.response import check_staleness
        from sylvan.tools.support.token_counting import count_tokens

        ctx = get_context()
        session = ctx.session

        symbol = await Symbol.where(symbol_id=p.symbol_id).with_("file").first()
        if symbol is None:
            raise SymbolNotFoundError(symbol_id=p.symbol_id)

        source = await symbol.get_source()
        file_rec = symbol.file
        file_path = file_rec.path if file_rec else ""
        session.record_symbol_access(p.symbol_id, file_path)

        bundle: dict = {
            "symbol": SymbolPresenter.full(symbol, file_path=file_path, source=source),
        }

        if p.include_imports:
            imports = await FileImport.where(file_id=symbol.file_id).get()
            bundle["imports"] = [ImportPresenter.standard(imp) for imp in imports]

        if p.include_callers:
            caller_files = await (
                FileRecord.query()
                .select("DISTINCT files.path", "files.language")
                .join("file_imports fi", "fi.file_id = files.id")
                .where("fi.resolved_file_id", symbol.file_id)
                .limit(20)
                .get()
            )
            bundle["callers"] = [FilePresenter.brief(c) for c in caller_files]

        siblings = await (
            Symbol.where(file_id=symbol.file_id).where_not(symbol_id=p.symbol_id).order_by("line_start").limit(10).get()
        )
        bundle["siblings"] = [SymbolPresenter.sibling(s) for s in siblings]

        self._returned_tokens = 0
        self._equivalent_tokens = 0
        self._used_tiktoken = False

        returned_text = json.dumps(bundle, default=str)
        token_count = count_tokens(returned_text)
        self._used_tiktoken = token_count is not None
        self._returned_tokens = token_count if token_count is not None else max(1, len(returned_text) // 4)
        if file_rec and file_rec.byte_size:
            self._equivalent_tokens = file_rec.byte_size // 4

        meta = get_meta()
        meta.extra("has_imports", bool(bundle.get("imports")))
        meta.extra("has_callers", bool(bundle.get("callers")))
        meta.extra("siblings_count", len(bundle["siblings"]))

        repo_name = await symbol._resolve_repo_name()
        self.hints().for_symbol(
            symbol_id=symbol.symbol_id,
            file_path=file_path,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            repo=repo_name or None,
        ).apply(bundle)

        if file_rec:
            await check_staleness(file_rec.repo_id, bundle)

        return bundle

    def measure(self, result: dict) -> tuple[int, int]:
        returned = getattr(self, "_returned_tokens", 0)
        equivalent = getattr(self, "_equivalent_tokens", 0)
        if returned > 0 and equivalent > 0:
            return returned, equivalent
        return 0, 0

    def measure_method(self) -> str:
        if getattr(self, "_used_tiktoken", False):
            return MeasureMethod.TIKTOKEN_CL100K
        return MeasureMethod.BYTE_ESTIMATE
