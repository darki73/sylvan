"""Write proxy -- forwards write operations from followers to the leader."""

import httpx

from sylvan.cluster.state import get_cluster_state
from sylvan.logging import get_logger

logger = get_logger(__name__)

# Tools that perform writes and need to be proxied
WRITE_TOOLS = frozenset({
    "index_folder",
    "index_file",
    "index_workspace",
    "add_library",
    "remove_library",
    "add_to_workspace",
    "pin_library",
    "remove_repo",
})


def is_write_tool(tool_name: str) -> bool:
    """Check if a tool performs write operations.

    Args:
        tool_name: MCP tool name to check.

    Returns:
        True if the tool modifies the database and must be proxied.
    """
    return tool_name in WRITE_TOOLS


async def proxy_to_leader(tool_name: str, arguments: dict) -> dict:
    """Forward a write tool call to the leader over HTTP.

    Args:
        tool_name: The MCP tool name.
        arguments: The tool arguments dict.

    Returns:
        The tool response dict from the leader.
    """
    state = get_cluster_state()
    if not state.leader_url:
        return {"error": "no_leader", "detail": "No leader URL configured. Cannot proxy write operation."}

    url = f"{state.leader_url}/api/proxy"

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json={
                "tool": tool_name,
                "arguments": arguments,
                "session_id": state.session_id,
            })
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError:
        logger.warning("leader_unreachable", url=url, tool=tool_name)
        return {"error": "leader_unreachable", "detail": "Could not connect to leader. It may have shut down."}
    except Exception as e:
        logger.warning("proxy_failed", tool=tool_name, error=str(e))
        return {"error": "proxy_failed", "detail": str(e)}
