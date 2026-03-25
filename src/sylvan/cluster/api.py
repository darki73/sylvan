"""Cluster API -- HTTP endpoints on the leader for write proxying and heartbeats."""

from starlette.requests import Request
from starlette.responses import JSONResponse

from sylvan.logging import get_logger

logger = get_logger(__name__)


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
    logger.debug("heartbeat_received", session_id=session_id)
    return JSONResponse({"status": "ok"})
