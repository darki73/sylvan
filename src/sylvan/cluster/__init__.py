"""Cluster module -- multi-instance leader/follower coordination."""

# Tools that perform writes and must be proxied to the leader
WRITE_TOOLS = frozenset(
    {
        "index_project",
        "reindex_file",
        "index_multi_repo",
        "index_library_source",
        "remove_library",
        "add_repo_to_workspace",
        "pin_library_version",
        "delete_repo_index",
        "find_tech_debt",
        "code_health_report",
    }
)


def is_write_tool(tool_name: str) -> bool:
    """Check if a tool performs write operations.

    Args:
        tool_name: The MCP tool name to check.

    Returns:
        True if the tool writes to the database and should be proxied.
    """
    return tool_name in WRITE_TOOLS
