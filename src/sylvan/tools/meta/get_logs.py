"""MCP tool: get_logs - retrieve sylvan server log entries."""

from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


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
    meta = MetaBuilder()
    lines = max(1, min(lines, 500))

    from sylvan.logging import _get_log_dir

    log_file = _get_log_dir() / "sylvan.log"

    if not log_file.exists():
        return wrap_response(
            {"entries": [], "message": "No log file found."},
            meta.build(),
        )

    try:
        all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as error:
        return wrap_response(
            {"entries": [], "error": f"Failed to read log file: {error}"},
            meta.build(),
        )

    total = len(all_lines)

    if from_start:
        result = all_lines[offset : offset + lines]
    else:
        end = total - offset
        start = max(0, end - lines)
        result = all_lines[start:end] if end > 0 else []

    meta.set("total_lines", total)
    meta.set("returned_lines", len(result))
    meta.set("offset", offset)
    meta.set("from_start", from_start)
    meta.set("log_file", str(log_file))

    return wrap_response({"entries": result}, meta.build())
