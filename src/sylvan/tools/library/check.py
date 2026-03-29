"""MCP tool: check_library_versions - compare installed vs indexed library versions."""

from sylvan.tools.support.response import get_meta, log_tool_call, wrap_response


@log_tool_call
async def check_library_versions(repo: str) -> dict:
    """Compare a project's installed dependencies against indexed library versions.

    Reads the project's dependency files (pyproject.toml, package.json, etc.)
    and cross-references each dependency against the sylvan library index.
    Reports which libraries are outdated, up-to-date, or not indexed.

    The agent uses this after running ``uv sync`` or ``npm install`` to
    detect version drift and decide which libraries to update in sylvan.

    Args:
        repo: Indexed repository name to check dependencies for.

    Returns:
        Tool response dict with ``outdated``, ``up_to_date``, and
        ``not_indexed`` lists plus ``_meta`` envelope.
    """
    meta = get_meta()

    from sylvan.services.library import check_versions as _svc

    result = await _svc(repo)

    if "error" in result:
        return wrap_response(result, meta.build())

    for key in ("total_deps", "outdated_count", "up_to_date_count", "not_indexed_count"):
        if key in result:
            meta.set(key, result.pop(key))

    return wrap_response(result, meta.build())
