"""MCP tool: get_logs - retrieve sylvan server log entries."""

from sylvan.tools.support.response import get_meta, log_tool_call, wrap_response


@log_tool_call
async def get_logs(
    lines: int = 50,
    from_start: bool = False,
    offset: int = 0,
) -> dict:
    """Retrieve log entries from the sylvan server log.

    Reads from ``~/.sylvan/logs/sylvan.log``. By default returns the
    last N lines (tail). Set ``from_start=True`` to read from the
    beginning (head). Use ``offset`` to paginate through the log.

    Args:
        lines: Number of lines to return. Clamped to 1-500.
        from_start: If True, read from the beginning instead of the end.
        offset: Skip this many lines before reading. For tail mode,
            offset counts backwards from the end.

    Returns:
        Tool response dict with ``entries`` list and ``_meta`` envelope.
    """
    meta = get_meta()

    from sylvan.services.meta import get_logs as _svc

    result = await _svc(lines=lines, from_start=from_start, offset=offset)

    meta.set("total_lines", result.get("total_lines", 0))
    meta.set("returned_lines", result.get("returned_lines", 0))
    meta.set("offset", result.get("offset", offset))
    meta.set("from_start", result.get("from_start", from_start))
    if "log_file" in result:
        meta.set("log_file", result.pop("log_file"))

    # Remove meta-level keys from body
    for key in ("total_lines", "returned_lines", "offset", "from_start"):
        result.pop(key, None)

    return wrap_response(result, meta.build())
