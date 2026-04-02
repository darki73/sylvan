"""MCP tool: index_file -- surgical single-file reindex."""

from __future__ import annotations

from typing import Any

from sylvan.tools.base import HasFilePath, HasRepo, Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class IndexFile(Tool):
    name = "index_file"
    category = "indexing"
    description = (
        "Surgical single-file reindex -- much faster than index_folder when you've "
        "only edited one file. Use after editing a file to keep the index current."
    )

    class Params(HasRepo, HasFilePath, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.error_codes import SylvanError
        from sylvan.services.indexing import index_file as _svc

        try:
            result = await _svc(p.repo, p.file_path)
        except SylvanError as exc:
            exc._meta = {}
            raise

        if "error" in result:
            return result

        meta = get_meta()
        meta.extra("status", result.get("status", "updated"))
        meta.symbols_extracted(result.get("symbols_extracted", 0))

        return result


async def index_file(**kwargs: Any) -> dict:
    return await IndexFile().execute(kwargs)
