"""MCP tool: index_folder -- index a local folder."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import Tool, ToolParams, schema_field


class IndexFolder(Tool):
    name = "index_folder"
    category = "indexing"
    description = (
        "REQUIRED FIRST STEP: Index a local folder before exploring its code or docs. "
        "Run this once per project, and RE-RUN after making code changes (edits, "
        "new files, refactors) to keep the index current -- incremental reindex is "
        "fast and only processes changed files. After indexing, ALWAYS prefer sylvan "
        "tools (search_symbols, get_symbol, get_file_outline, search_sections) over "
        "reading files directly with Read/cat. Sylvan returns only the exact code "
        "you need instead of entire files. "
        "For third-party libraries, use add_library instead (fetches source from PyPI/npm/etc)."
    )

    class Params(ToolParams):
        path: str = schema_field(
            description="Absolute path to the folder to index",
        )
        name: str | None = schema_field(
            default=None,
            description="Display name for the repository (defaults to folder name)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.indexing import index_folder as _svc
        from sylvan.tools.base.meta import get_meta

        result = await _svc(p.path, name=p.name)

        meta = get_meta()
        meta.repo(result.get("repo", ""))
        meta.files_indexed(result.get("files_indexed", 0))
        meta.symbols_extracted(result.get("symbols_extracted", 0))

        return result


async def index_folder(
    path: str | None = None,
    name: str | None = None,
    **kwargs: Any,
) -> dict:
    if path is not None:
        kwargs["path"] = path
    if name is not None:
        kwargs["name"] = name
    return await IndexFolder().execute(kwargs)
