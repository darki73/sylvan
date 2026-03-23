"""Cluster API -- HTTP endpoints on the leader for write proxying and session management."""

from datetime import UTC, datetime

from starlette.requests import Request
from starlette.responses import JSONResponse

from sylvan.logging import get_logger

logger = get_logger(__name__)

# In-memory session registry (supplemented by DB persistence)
_registered_sessions: dict[str, dict] = {}


async def handle_proxy(request: Request) -> JSONResponse:
    """Execute a proxied tool call from a follower.

    The follower sends the tool name + arguments, and we execute it
    locally using the leader's dispatch function.

    Args:
        request: The incoming HTTP request with tool name and arguments.

    Returns:
        JSON response with the tool result.
    """
    body = await request.json()
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})
    follower_session = body.get("session_id", "unknown")

    logger.info("proxy_call", tool=tool_name, from_session=follower_session)

    from sylvan.session.tracker import get_session
    get_session()._workflow_loaded = True

    from sylvan.server import _dispatch

    try:
        result = await _dispatch(tool_name, arguments)
        return JSONResponse(result)
    except Exception as e:
        logger.error("proxy_call_failed", tool=tool_name, error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_heartbeat(request: Request) -> JSONResponse:
    """Receive a heartbeat from a follower with its session stats.

    Args:
        request: The incoming HTTP request with session stats payload.

    Returns:
        JSON acknowledgement.
    """
    body = await request.json()
    session_id = body.get("session_id", "")

    _registered_sessions[session_id] = {
        "session_id": session_id,
        "stats": body.get("stats", {}),
        "efficiency": body.get("efficiency", {}),
        "cache": body.get("cache", {}),
        "last_heartbeat": datetime.now(UTC).isoformat(),
    }

    return JSONResponse({"status": "ok"})


async def handle_session_register(request: Request) -> JSONResponse:
    """Register a new follower session.

    Args:
        request: The incoming HTTP request with session metadata.

    Returns:
        JSON acknowledgement.
    """
    body = await request.json()
    session_id = body.get("session_id", "")
    _registered_sessions[session_id] = {
        "session_id": session_id,
        "pid": body.get("pid"),
        "role": "follower",
        "started_at": body.get("started_at"),
        "last_heartbeat": datetime.now(UTC).isoformat(),
        "stats": {},
        "efficiency": {},
        "cache": {},
    }
    logger.info("session_registered", session_id=session_id)
    return JSONResponse({"status": "registered"})


async def handle_session_deregister(request: Request) -> JSONResponse:
    """Deregister a follower session on shutdown.

    Args:
        request: The incoming HTTP request with session_id path param.

    Returns:
        JSON acknowledgement.
    """
    session_id = request.path_params.get("session_id", "")
    _registered_sessions.pop(session_id, None)
    logger.info("session_deregistered", session_id=session_id)
    return JSONResponse({"status": "deregistered"})


def get_all_sessions() -> list[dict]:
    """Get all registered follower sessions.

    Returns:
        List of session info dicts from the in-memory registry.
    """
    return list(_registered_sessions.values())
