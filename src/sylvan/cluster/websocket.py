"""Cluster WebSocket -- leader server and follower client.

The leader runs a WebSocket endpoint that followers connect to.
All cluster communication flows through this single persistent channel:
pings, write proxying, stats, logs, and step-down signals.
"""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from sylvan.cluster import protocol
from sylvan.logging import get_logger

logger = get_logger(__name__)

# Leader-side: connected follower websockets
_followers: dict[str, WebSocket] = {}
_leader_ping_task: asyncio.Task | None = None


# ── Leader side ──────────────────────────────────────────────────────


async def handle_follower_connection(websocket: WebSocket) -> None:
    """Handle a new follower WebSocket connection (leader-side).

    Accepts the connection, processes messages until disconnect,
    and cleans up on exit.

    Args:
        websocket: The incoming Starlette WebSocket.
    """
    await websocket.accept()
    follower_id = None

    try:
        # First message should identify the follower
        raw = await websocket.receive_text()
        msg = protocol.decode(raw)
        follower_id = msg.get("node_id", "unknown")
        _followers[follower_id] = websocket
        logger.info("follower_connected", follower_id=follower_id, total=len(_followers))

        while True:
            raw = await websocket.receive_text()
            msg = protocol.decode(raw)
            await _handle_leader_message(websocket, follower_id, msg)

    except WebSocketDisconnect:
        logger.info("follower_disconnected", follower_id=follower_id)
    except Exception as exc:
        logger.warning("follower_connection_error", follower_id=follower_id, error=str(exc))
    finally:
        if follower_id and follower_id in _followers:
            del _followers[follower_id]


async def _handle_leader_message(websocket: WebSocket, follower_id: str, msg: dict[str, Any]) -> None:
    """Process a message received by the leader from a follower.

    Args:
        websocket: The follower's WebSocket connection.
        follower_id: The follower's node identifier.
        msg: The decoded message dict.
    """
    msg_type = msg.get("type")

    if msg_type == protocol.MSG_PONG:
        return

    if msg_type == protocol.MSG_WRITE:
        request_id = msg.get("id", "")
        tool = msg.get("tool", "")
        args = msg.get("args", {})
        logger.info("proxy_write", follower=follower_id, tool=tool, request_id=request_id)
        try:
            from sylvan.server import _dispatch

            result = await _dispatch(tool, args)
            await websocket.send_text(protocol.write_result(request_id, data=result))
        except Exception as exc:
            logger.warning("proxy_write_failed", tool=tool, error=str(exc))
            await websocket.send_text(protocol.write_result(request_id, error=str(exc)))

    elif msg_type == protocol.MSG_STATS:
        # Leader persists follower stats
        node_id = msg.get("node_id", follower_id)
        logger.debug("stats_received", from_node=node_id)

    elif msg_type == protocol.MSG_LOG:
        lines = msg.get("lines", [])
        if lines:
            logger.debug("log_received", from_node=follower_id, count=len(lines))


async def start_leader_pings(interval: int = 2) -> None:
    """Start the background ping loop for all connected followers.

    Args:
        interval: Seconds between pings.
    """
    global _leader_ping_task

    async def _ping_loop():
        while True:
            await asyncio.sleep(interval)
            dead = []
            for fid, ws in _followers.items():
                try:
                    await ws.send_text(protocol.ping())
                except Exception:
                    dead.append(fid)
            for fid in dead:
                _followers.pop(fid, None)
                logger.info("follower_ping_failed", follower_id=fid)

    _leader_ping_task = asyncio.ensure_future(_ping_loop())


async def broadcast_step_down(new_leader: str | None = None) -> None:
    """Send step-down message to all connected followers.

    Args:
        new_leader: Optional node ID of the new leader.
    """
    import contextlib

    msg = protocol.step_down(new_leader)
    for _fid, ws in list(_followers.items()):
        with contextlib.suppress(Exception):
            await ws.send_text(msg)
    logger.info("step_down_broadcast", followers=len(_followers))


def stop_leader_pings() -> None:
    """Cancel the leader ping task."""
    global _leader_ping_task
    if _leader_ping_task is not None:
        _leader_ping_task.cancel()
        _leader_ping_task = None


# ── Follower side ────────────────────────────────────────────────────

_follower_ws: Any = None
_follower_task: asyncio.Task | None = None
_pending_writes: dict[str, asyncio.Future] = {}


async def connect_to_leader(leader_url: str, node_id: str, on_step_down: Any = None) -> None:
    """Connect to the leader's WebSocket endpoint as a follower.

    Maintains the connection in a background task with auto-reconnect.

    Args:
        leader_url: The leader's WebSocket URL (ws://...).
        node_id: This follower's node identifier.
        on_step_down: Optional async callback when leader steps down.
    """
    global _follower_task

    async def _run():
        global _follower_ws
        import websockets

        while True:
            try:
                ws_url = leader_url.replace("http://", "ws://") + "/ws/cluster"
                async with websockets.connect(ws_url) as ws:
                    _follower_ws = ws
                    # Identify ourselves
                    await ws.send(protocol.encode({"type": "identify", "node_id": node_id}))
                    logger.info("connected_to_leader", url=ws_url)

                    async for raw in ws:
                        msg = protocol.decode(raw)
                        await _handle_follower_message(msg, on_step_down)

            except Exception as exc:
                logger.warning("leader_connection_lost", error=str(exc))
                _follower_ws = None
                # Reject pending writes
                for fut in _pending_writes.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("Leader connection lost"))
                _pending_writes.clear()
                await asyncio.sleep(2)

    _follower_task = asyncio.ensure_future(_run())


async def _handle_follower_message(msg: dict[str, Any], on_step_down: Any = None) -> None:
    """Process a message received by the follower from the leader.

    Args:
        msg: The decoded message dict.
        on_step_down: Optional async callback for step-down signals.
    """
    msg_type = msg.get("type")

    if msg_type == protocol.MSG_PING:
        if _follower_ws:
            await _follower_ws.send(protocol.pong())

    elif msg_type == protocol.MSG_RESULT:
        request_id = msg.get("id", "")
        future = _pending_writes.pop(request_id, None)
        if future and not future.done():
            if "error" in msg:
                future.set_exception(RuntimeError(msg["error"]))
            else:
                future.set_result(msg.get("data", {}))

    elif msg_type == protocol.MSG_STEP_DOWN:
        logger.info("leader_stepping_down", new_leader=msg.get("new_leader"))
        if on_step_down:
            await on_step_down(msg.get("new_leader"))


async def proxy_to_leader(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Forward a write tool call to the leader over WebSocket.

    Args:
        tool_name: The MCP tool name.
        arguments: The tool arguments dict.

    Returns:
        The tool response dict from the leader.

    Raises:
        ConnectionError: If not connected to the leader.
        RuntimeError: If the leader returns an error.
    """
    if _follower_ws is None:
        return {"error": "leader_unreachable", "detail": "Not connected to leader WebSocket."}

    request_id = protocol.make_id()
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending_writes[request_id] = future

    try:
        await _follower_ws.send(protocol.write_request(tool_name, arguments, request_id))
        return await asyncio.wait_for(future, timeout=120)
    except TimeoutError:
        _pending_writes.pop(request_id, None)
        return {"error": "proxy_timeout", "detail": "Leader did not respond within 120 seconds."}
    except Exception as exc:
        _pending_writes.pop(request_id, None)
        return {"error": "proxy_failed", "detail": str(exc)}


def disconnect_from_leader() -> None:
    """Cancel the follower connection task."""
    global _follower_task, _follower_ws
    if _follower_task is not None:
        _follower_task.cancel()
        _follower_task = None
    _follower_ws = None
