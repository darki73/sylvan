"""MCP tool: rename_symbol -- find all edit locations for renaming a symbol."""

from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def rename_symbol(symbol_id: str, new_name: str) -> dict:
    """Find all files and lines where a symbol name appears for renaming.

    Looks up the symbol, uses blast radius analysis to find affected files,
    then scans each file for occurrences of the old name. Returns exact
    edit locations (file, line, old_text, new_text) for the agent to apply.

    Args:
        symbol_id: The symbol identifier to rename.
        new_name: The desired new name for the symbol.

    Returns:
        Tool response dict with ``edits`` list, ``symbol`` info,
        and ``_meta`` envelope with counts.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.services.analysis import AnalysisService

    result = await AnalysisService().rename_symbol(symbol_id, new_name)

    if "error" in result:
        return wrap_response(result, meta.build())

    meta.set("affected_files", result.pop("affected_files"))
    meta.set("total_edits", result.pop("total_edits"))
    meta.set("old_name", result["symbol"]["name"])
    meta.set("new_name", result["new_name"])

    return wrap_response(result, meta.build())
