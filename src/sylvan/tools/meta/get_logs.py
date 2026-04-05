"""MCP tool: get_logs -- retrieve sylvan server log entries."""

from sylvan.tools.base import Tool, ToolParams, schema_field


class GetLogs(Tool):
    name = "server_logs"
    category = "meta"
    description = (
        "Returns sylvan server log entries. Defaults to most recent lines (tail). "
        "Supports from_start for head and offset for pagination."
    )

    class Params(ToolParams):
        lines: int = schema_field(
            default=50,
            ge=1,
            le=500,
            description="Number of lines to return (1-500, default 50)",
        )
        from_start: bool = schema_field(
            default=False,
            description="Read from beginning instead of end",
        )
        offset: int = schema_field(
            default=0,
            description="Skip this many lines before reading",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.meta import get_logs as _svc
        from sylvan.tools.base.meta import get_meta

        result = await _svc(lines=p.lines, from_start=p.from_start, offset=p.offset)

        meta = get_meta()
        meta.extra("total_lines", result.get("total_lines", 0))
        meta.extra("returned_lines", result.get("returned_lines", 0))
        meta.extra("offset", result.get("offset", p.offset))
        meta.extra("from_start", result.get("from_start", p.from_start))
        if "log_file" in result:
            meta.extra("log_file", result.pop("log_file"))

        for key in ("total_lines", "returned_lines", "offset", "from_start"):
            result.pop(key, None)

        return result


async def get_logs(
    lines: int = 50,
    from_start: bool = False,
    offset: int = 0,
    **_kwargs: object,
) -> dict:
    return await GetLogs().execute(
        {
            "lines": lines,
            "from_start": from_start,
            "offset": offset,
        }
    )
