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
        follower_pid = msg.get("pid", 0)
        _followers[follower_id] = websocket
        logger.info("follower_connected", follower_id=follower_id, pid=follower_pid, total=len(_followers))

        await _register_follower_node(follower_id, follower_pid)

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
        if follower_id:
            await _unregister_follower_node(follower_id)


async def _register_follower_node(follower_id: str, pid: int = 0) -> None:
    """Register a follower node in the DB (leader-side).

    Args:
        follower_id: The follower's node identifier.
        pid: The follower's OS process ID.
    """
    try:
        from datetime import UTC, datetime

        from sylvan.cluster.state import get_cluster_state
        from sylvan.database.orm import ClusterNode
        from sylvan.database.orm.runtime.connection_manager import get_backend

        now = datetime.now(UTC).isoformat()
        state = get_cluster_state()
        backend = get_backend()

        existing = await ClusterNode.where(node_id=follower_id).first()
        if existing is None:
            await ClusterNode.create(
                node_id=follower_id,
                pid=pid,
                role="follower",
                connected_at=now,
                last_seen=now,
                coding_session_id=state.coding_session_id,
            )
        elif existing.role != "leader":
            await existing.update(role="follower", last_seen=now)

        await backend.commit()
        logger.info("follower_registered_in_db", follower_id=follower_id)
    except Exception as exc:
        logger.warning("follower_registration_failed", follower_id=follower_id, error=str(exc))


async def _unregister_follower_node(follower_id: str) -> None:
    """Remove a follower node from the DB on disconnect (leader-side).

    Args:
        follower_id: The follower's node identifier.
    """
    try:
        from sylvan.database.orm import ClusterNode
        from sylvan.database.orm.runtime.connection_manager import get_backend

        await ClusterNode.where(node_id=follower_id).delete()
        await get_backend().commit()
    except Exception as exc:
        logger.debug("follower_unregistration_failed", follower_id=follower_id, error=str(exc))


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
        node_id = msg.get("node_id", follower_id)
        stats = msg.get("stats", {})
        efficiency = msg.get("efficiency", {})
        cache_data = msg.get("cache", {})
        try:
            from sylvan.cluster.state import get_cluster_state as _get_state
            from sylvan.database.orm import Instance

            _inst_data = {
                "tool_calls": stats.get("tool_calls", 0),
                "tokens_returned": stats.get("tokens_returned", 0),
                "tokens_avoided": stats.get("tokens_avoided", 0),
                "efficiency_returned": efficiency.get("total_returned", 0),
                "efficiency_equivalent": efficiency.get("total_equivalent", 0),
                "symbols_retrieved": stats.get("symbols_retrieved", 0),
                "sections_retrieved": stats.get("sections_retrieved", 0),
                "queries": stats.get("queries", 0),
                "cache_hits": cache_data.get("hits", 0),
                "cache_misses": cache_data.get("misses", 0),
                "category_data": efficiency.get("by_category", {}),
            }

            instance = await Instance.where(node_id=node_id).where_null("ended_at").first()
            if instance:
                await instance.update(**_inst_data)
            else:
                await Instance.create(
                    instance_id=node_id,
                    node_id=node_id,
                    coding_session_id=_get_state().coding_session_id,
                    started_at=stats.get("start_time", ""),
                    **_inst_data,
                )
            from datetime import UTC, datetime

            from sylvan.database.orm import ClusterNode
            from sylvan.database.orm.runtime.connection_manager import get_backend

            await ClusterNode.where(node_id=node_id).update(last_seen=datetime.now(UTC).isoformat())
            await get_backend().commit()

            # Push updated cluster stats + combined efficiency to dashboard
            from sylvan.dashboard.app import _get_cluster_sessions
            from sylvan.events import emit as _emit_cluster_update

            cluster_sessions = await _get_cluster_sessions()
            _cs = _get_state()

            from sylvan.dashboard.app import _combine_session_efficiency

            _combined = _combine_session_efficiency(cluster_sessions) or {}

            _emit_cluster_update(
                "stats_update",
                {
                    "cluster": {
                        "role": _cs.role,
                        "session_id": _cs.session_id,
                        "coding_session_id": _cs.coding_session_id,
                        "nodes": cluster_sessions,
                        "active_count": sum(1 for s in cluster_sessions if s.get("alive")),
                        "total_tool_calls": sum(s.get("tool_calls", 0) for s in cluster_sessions),
                    },
                    "efficiency": _combined,
                },
            )
            logger.debug("follower_stats_updated", from_node=node_id, tool_calls=stats.get("tool_calls", 0))
        except Exception as exc:
            logger.debug("follower_stats_update_failed", from_node=node_id, error=str(exc))

    elif msg_type == "usage":
        data = msg.get("data", {})
        try:
            from sylvan.session.usage_stats import _write_to_db

            await _write_to_db(**data)
            logger.debug("usage_recorded_for_follower", from_node=follower_id, repo_id=data.get("repo_id"))
        except Exception as exc:
            logger.debug("usage_record_failed", from_node=follower_id, error=str(exc))

    elif msg_type == protocol.MSG_LOG:
        lines = msg.get("lines", [])
        if lines:
            logger.debug("log_received", from_node=follower_id, count=len(lines))


async def start_leader_pings(interval: int = 2) -> None:
    """Start the background ping loop for all connected followers.

    Args:
        interval: Seconds between pings.
    """

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

    from sylvan.server.lifecycle import get_lifecycle

    lifecycle = get_lifecycle()
    if lifecycle:
        lifecycle.spawn(_ping_loop(), name="leader_pings")
    else:
        asyncio.ensure_future(_ping_loop())


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


_follower_ws: Any = None
_follower_task: asyncio.Task | None = None
_pending_writes: dict[str, asyncio.Future] = {}
_node_id: str = ""
_coding_session_id: str = ""


async def stop_follower_connection() -> None:
    """Cancel the follower WebSocket client task.

    Called during promotion to prevent the node from reconnecting
    to itself as a follower after it becomes the new leader.
    """
    global _follower_task, _follower_ws
    if _follower_task is not None:
        _follower_task.cancel()
        _follower_task = None
    _follower_ws = None


async def send_usage_to_leader(usage_data: dict) -> None:
    """Send usage stats to the leader for DB recording.

    Args:
        usage_data: Dict with repo_id and stat fields.
    """
    if _follower_ws is None:
        return
    import json

    msg = json.dumps({"type": "usage", "data": usage_data})
    try:
        await _follower_ws.send(msg)
    except Exception as exc:
        logger.debug("usage_send_failed", error=str(exc))


async def connect_to_leader(leader_url: str, node_id: str, on_step_down: Any = None) -> None:
    """Connect to the leader's WebSocket endpoint as a follower.

    Uses websockets' built-in auto-reconnect iterator. On each successful
    connection, identifies the follower and processes messages until disconnect.
    Reconnection with exponential backoff is handled automatically.

    Args:
        leader_url: The leader's HTTP URL (auto-converted to ws://).
        node_id: This follower's node identifier.
        on_step_down: Optional async callback when leader steps down.
    """

    async def _run():
        global _follower_ws, _node_id, _coding_session_id
        from websockets.asyncio.client import connect

        from sylvan.cluster.state import get_cluster_state

        state = get_cluster_state()
        _node_id = node_id
        _coding_session_id = state.coding_session_id

        ws_url = leader_url.replace("http://", "ws://") + "/ws/cluster"

        try:
            async for ws in connect(ws_url, ping_interval=None, compression=None):
                try:
                    _follower_ws = ws
                    import os

                    await ws.send(protocol.encode({"type": "identify", "node_id": node_id, "pid": os.getpid()}))
                    logger.info("connected_to_leader", url=ws_url)

                    async for raw in ws:
                        msg = protocol.decode(raw)
                        await _handle_follower_message(msg, on_step_down)

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("leader_connection_lost", error=str(exc))
                finally:
                    _follower_ws = None
                    for fut in _pending_writes.values():
                        if not fut.done():
                            fut.set_exception(ConnectionError("Leader connection lost"))
                    _pending_writes.clear()
        except asyncio.CancelledError:
            pass

    global _follower_task

    from sylvan.server.lifecycle import get_lifecycle

    lifecycle = get_lifecycle()
    if lifecycle:
        _follower_task = lifecycle.spawn(_run(), name="follower_ws")
    else:
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
        else:
            from sylvan.cluster.heartbeat import _try_promote
            from sylvan.database.orm.runtime.connection_manager import get_backend

            await _try_promote(get_backend(), _node_id, _coding_session_id)


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
    future: asyncio.Future = asyncio.get_running_loop().create_future()
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
