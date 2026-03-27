"""Cluster module -- multi-instance leader/follower coordination."""

# Tools that perform writes and must be proxied to the leader
WRITE_TOOLS = frozenset(
    {
        "index_folder",
        "index_file",
        "index_workspace",
        "add_library",
        "remove_library",
        "add_to_workspace",
        "pin_library",
        "remove_repo",
        "get_quality",
        "get_quality_report",
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
