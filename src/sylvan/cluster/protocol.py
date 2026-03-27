"""Cluster WebSocket protocol -- message types and serialization.

All inter-node communication uses JSON messages over a single WebSocket.
Each message has a ``type`` field that determines its structure.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

# Message types
MSG_PING = "ping"
MSG_PONG = "pong"
MSG_STEP_DOWN = "step_down"
MSG_WRITE = "write"
MSG_RESULT = "result"
MSG_STATS = "stats"
MSG_LOG = "log"


def make_id() -> str:
    """Generate a unique message ID for request/response correlation.

    Returns:
        A short hex string.
    """
    return uuid.uuid4().hex[:8]


def encode(msg: dict[str, Any]) -> str:
    """Encode a message dict to a JSON string.

    Args:
        msg: The message to encode.

    Returns:
        JSON string.
    """
    return json.dumps(msg, separators=(",", ":"))


def decode(data: str) -> dict[str, Any]:
    """Decode a JSON string to a message dict.

    Args:
        data: The JSON string to decode.

    Returns:
        The parsed message dict.

    Raises:
        ValueError: If the data is not valid JSON.
    """
    return json.loads(data)


def ping() -> str:
    """Build a ping message (leader -> follower)."""
    return encode({"type": MSG_PING})


def pong() -> str:
    """Build a pong message (follower -> leader)."""
    return encode({"type": MSG_PONG})


def step_down(new_leader: str | None = None) -> str:
    """Build a step-down message (leader -> follower).

    Args:
        new_leader: Optional node ID of the new leader, if known.
    """
    msg: dict[str, Any] = {"type": MSG_STEP_DOWN}
    if new_leader:
        msg["new_leader"] = new_leader
    return encode(msg)


def write_request(tool: str, args: dict[str, Any], request_id: str | None = None) -> str:
    """Build a write proxy request (follower -> leader).

    Args:
        tool: The MCP tool name to execute.
        args: Tool arguments.
        request_id: Optional correlation ID (auto-generated if None).
    """
    return encode(
        {
            "type": MSG_WRITE,
            "id": request_id or make_id(),
            "tool": tool,
            "args": args,
        }
    )


def write_result(request_id: str, data: dict[str, Any] | None = None, error: str | None = None) -> str:
    """Build a write proxy result (leader -> follower).

    Args:
        request_id: The correlation ID from the write request.
        data: The tool result data (on success).
        error: The error message (on failure).
    """
    msg: dict[str, Any] = {"type": MSG_RESULT, "id": request_id}
    if error:
        msg["error"] = error
    else:
        msg["data"] = data or {}
    return encode(msg)


def stats_message(node_id: str, stats: dict[str, Any], efficiency: dict[str, Any], cache: dict[str, Any]) -> str:
    """Build a stats push message (follower -> leader).

    Args:
        node_id: The follower's node identifier.
        stats: Session stats dict.
        efficiency: Efficiency stats dict.
        cache: Cache stats dict.
    """
    return encode(
        {
            "type": MSG_STATS,
            "node_id": node_id,
            "stats": stats,
            "efficiency": efficiency,
            "cache": cache,
        }
    )


def log_message(lines: list[dict[str, Any]]) -> str:
    """Build a batched log message (follower -> leader).

    Args:
        lines: List of structured log entry dicts.
    """
    return encode({"type": MSG_LOG, "lines": lines})
