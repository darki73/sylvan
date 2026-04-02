"""MCP tool: add_library -- index a third-party library's source code."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import Tool, ToolParams, schema_field


class AddLibrary(Tool):
    name = "add_library"
    category = "meta"
    description = (
        "Index a third-party library's SOURCE CODE for precise API lookup. "
        "Fetches the real implementation at a specific version -- more reliable "
        "than documentation. When you encounter an unfamiliar library or need to "
        "look up how an API actually works, use this tool FIRST to index it, then "
        "search_symbols to find the implementation. "
        "Format: pip/django@4.2, npm/react@18, go/github.com/gin-gonic/gin, cargo/serde"
    )

    class Params(ToolParams):
        package: str = schema_field(
            description="Package spec: manager/name[@version] (e.g., pip/django@4.2, npm/react)",
        )

    async def handle(self, p: Params) -> dict:
        try:
            from sylvan.services.library import add_library as _svc
            from sylvan.tools.base.meta import get_meta

            result = await _svc(p.package)
            get_meta().extra("status", result.get("status", ""))
            return result
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to add library: {e}"}


async def add_library(**kwargs: Any) -> dict:
    return await AddLibrary().execute(kwargs)
