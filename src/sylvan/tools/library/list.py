"""MCP tool: list_libraries -- show all indexed third-party libraries."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class ListLibraries(Tool):
    name = "indexed_libraries"
    category = "meta"
    description = "Lists all indexed third-party libraries with name, version, and symbol count."

    class Params(ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.library import list_libraries as _svc

        libs = await _svc()
        get_meta().results_count(len(libs))
        return {"libraries": libs}


async def list_libraries(**kwargs: Any) -> dict:
    return await ListLibraries().execute(kwargs)
