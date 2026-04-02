"""MCP tool: check_library_versions -- compare installed vs indexed library versions."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import HasRepo, Tool, ToolParams


class CheckLibraryVersions(Tool):
    name = "check_library_versions"
    category = "meta"
    description = (
        "Compare a project's installed dependencies against indexed library "
        "versions. Reads pyproject.toml, package.json, go.mod, etc. and reports "
        "which libraries are outdated (installed version differs from indexed), "
        "up-to-date, or not indexed at all. Use after uv sync or npm install "
        "to detect version drift and decide which libraries to re-index."
    )

    class Params(HasRepo, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.library import check_versions as _svc
        from sylvan.tools.base.meta import get_meta

        result = await _svc(p.repo)

        if "error" in result:
            return result

        meta = get_meta()
        for key in ("total_deps", "outdated_count", "up_to_date_count", "not_indexed_count"):
            if key in result:
                meta.extra(key, result.pop(key))

        return result


async def check_library_versions(**kwargs: Any) -> dict:
    return await CheckLibraryVersions().execute(kwargs)
