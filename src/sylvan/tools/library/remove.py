"""MCP tool: remove_library -- remove an indexed library."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import Tool, ToolParams, schema_field


class RemoveLibrary(Tool):
    name = "remove_library"
    category = "meta"
    description = "Remove an indexed library and its source files from disk."

    class Params(ToolParams):
        name: str = schema_field(
            description="Library name (e.g., django@4.2)",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.library import remove_library as _svc
        from sylvan.tools.base.meta import get_meta

        result = await _svc(p.name)
        get_meta().extra("status", result.get("status", ""))
        return result


async def remove_library(**kwargs: Any) -> dict:
    return await RemoveLibrary().execute(kwargs)
