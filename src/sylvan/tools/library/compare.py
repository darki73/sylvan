"""MCP tool: compare_library_versions - diff symbols between two library versions."""

from sylvan.tools.support.response import get_meta, log_tool_call, wrap_response


@log_tool_call
async def compare_library_versions(
    package: str,
    from_version: str,
    to_version: str,
) -> dict:
    """Compare two indexed versions of the same library.

    Generates a migration-relevant diff: symbols added, removed, and
    changed (signature differences). The agent uses this to assess
    breaking changes before upgrading a workspace's pinned version.

    Both versions must already be indexed via ``add_library``.

    Args:
        package: Package name without manager prefix (e.g. ``"numpy"``).
        from_version: The old version string (e.g. ``"1.1.1"``).
        to_version: The new version string (e.g. ``"2.2.2"``).

    Returns:
        Tool response dict with added, removed, and changed symbol lists.
    """
    meta = get_meta()

    from sylvan.services.library import compare_versions as _svc

    result = await _svc(package, from_version, to_version)

    if "error" in result:
        return wrap_response(result, meta.build())

    summary = result.get("summary", {})
    meta.set("from_version", from_version)
    meta.set("to_version", to_version)
    meta.set("added_count", summary.get("total_added", 0))
    meta.set("removed_count", summary.get("total_removed", 0))
    meta.set("changed_count", summary.get("total_changed", 0))
    meta.set("breaking_risk", summary.get("breaking_risk", "low"))

    return wrap_response(result, meta.build())
