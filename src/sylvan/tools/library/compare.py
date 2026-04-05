"""MCP tool: compare_library_versions -- diff symbols between two library versions."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class CompareLibraryVersions(Tool):
    name = "migration_guide"
    category = "meta"
    description = (
        "Compares two indexed versions of a library. Returns symbols added, "
        "removed, and changed with signature diffs. Both versions must be "
        "indexed via index_library_source first."
    )

    class Params(ToolParams):
        package: str = schema_field(
            description="Package name without manager prefix (e.g., 'numpy', 'react')",
        )
        from_version: str = schema_field(
            description="The old version to compare from (e.g., '1.1.1')",
        )
        to_version: str = schema_field(
            description="The new version to compare to (e.g., '2.2.2')",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.library import compare_versions as _svc

        result = await _svc(p.package, p.from_version, p.to_version)

        if "error" in result:
            return result

        summary = result.get("summary", {})
        meta = get_meta()
        meta.extra("from_version", p.from_version)
        meta.extra("to_version", p.to_version)
        meta.extra("added_count", summary.get("total_added", 0))
        meta.extra("removed_count", summary.get("total_removed", 0))
        meta.extra("changed_count", summary.get("total_changed", 0))
        meta.extra("breaking_risk", summary.get("breaking_risk", "low"))

        return result


async def compare_library_versions(**kwargs: Any) -> dict:
    return await CompareLibraryVersions().execute(kwargs)
