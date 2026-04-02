"""MCP tool: list_libraries -- show all indexed third-party libraries."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class ListLibraries(Tool):
    name = "list_libraries"
    category = "meta"
    description = (
        "List all indexed third-party libraries. Check this to see what library "
        "source code is available for search. If a library you need isn't listed, "
        "use add_library to index it."
    )

    class Params(ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.library import list_libraries as _svc

        libs = await _svc()
        get_meta().results_count(len(libs))
        return {"libraries": libs}


async def list_libraries(**kwargs: Any) -> dict:
    return await ListLibraries().execute(kwargs)
