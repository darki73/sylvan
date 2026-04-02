"""MCP tools: get_file_outline, get_file_outlines -- hierarchical symbol outlines."""

from __future__ import annotations

import json

from sylvan.tools.base import (
    HasFilePath,
    HasFilePaths,
    HasRepo,
    MeasureMethod,
    Tool,
    ToolParams,
)
from sylvan.tools.base.meta import get_meta


class GetFileOutline(Tool):
    name = "get_file_outline"
    category = "retrieval"
    description = (
        "PREFERRED over Read for understanding a file's structure. Returns a "
        "hierarchical outline of all symbols (functions, classes, methods) with "
        "signatures and line numbers -- without reading the file content. Use this "
        "BEFORE reading a file to understand what's in it, then use get_symbol "
        "to fetch only the specific symbol you need."
    )

    class Params(HasRepo, HasFilePath, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.symbol import SymbolService
        from sylvan.tools.support.response import check_staleness
        from sylvan.tools.support.token_counting import count_tokens

        data = await SymbolService().file_outline(p.repo, p.file_path)

        repo_id = data.pop("repo_id")
        file_rec = data.pop("file_rec")
        symbol_count = data.pop("symbol_count")

        self._returned_tokens = 0
        self._equivalent_tokens = 0
        self._used_tiktoken = False

        returned_text = json.dumps(data["outline"], default=str)
        token_count = count_tokens(returned_text)
        self._used_tiktoken = token_count is not None
        self._returned_tokens = token_count if token_count is not None else max(1, len(returned_text) // 4)
        if file_rec.byte_size:
            self._equivalent_tokens = file_rec.byte_size // 4

        get_meta().extra("symbol_count", symbol_count)
        result = {**data}
        await check_staleness(repo_id, result)

        outline = result.get("outline", [])
        for entry in outline:
            if entry.get("kind") in ("function", "method"):
                self.hints().next_symbol(entry["symbol_id"]).apply(result)
                break

        return result

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


class GetFileOutlines(Tool):
    name = "get_file_outlines"
    category = "retrieval"
    description = (
        "Batch retrieve outlines for multiple files in ONE call. More efficient "
        "than calling get_file_outline repeatedly. Returns symbol trees for each "
        "file with signatures and line numbers."
    )

    class Params(HasRepo, HasFilePaths, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.symbol import SymbolService
        from sylvan.tools.support.response import check_staleness
        from sylvan.tools.support.token_counting import count_tokens

        data = await SymbolService().file_outlines(p.repo, p.file_paths)

        repo_id = data.pop("repo_id")

        self._returned_tokens = 0
        self._equivalent_tokens = 0
        self._used_tiktoken = False

        cleaned_outlines = []
        for outline_entry in data["outlines"]:
            file_rec = outline_entry.pop("file_rec")
            outline_text = json.dumps(outline_entry["outline"], default=str)
            token_count = count_tokens(outline_text)
            if token_count is not None:
                self._used_tiktoken = True
            self._returned_tokens += token_count if token_count is not None else max(1, len(outline_text) // 4)
            if file_rec.byte_size:
                self._equivalent_tokens += file_rec.byte_size // 4
            cleaned_outlines.append(outline_entry)

        meta = get_meta()
        meta.found(len(cleaned_outlines))
        meta.not_found_count(len(data["not_found"]))

        result = {
            "outlines": cleaned_outlines,
            "not_found": data["not_found"],
        }
        await check_staleness(repo_id, result)
        return result

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
