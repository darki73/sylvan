"""Heartbeat -- node registration, stats persistence, dead instance cleanup."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

from sylvan.cluster.discovery import _is_pid_alive
from sylvan.cluster.state import get_cluster_state
from sylvan.logging import get_logger

logger = get_logger(__name__)


async def ensure_coding_session(backend, coding_session_id: str) -> None:
    """Create the coding session row if it doesn't exist, and increment spawn count.

    Args:
        backend: The async storage backend.
        coding_session_id: The coding session identifier.
    """
    from sylvan.database.orm import CodingSession

    existing = await CodingSession.where(id=coding_session_id).first()
    if existing is None:
        now = datetime.now(UTC).isoformat()
        await CodingSession.create(
            id=coding_session_id,
            started_at=now,
            instances_spawned=1,
        )
    else:
        await CodingSession.where(id=coding_session_id).increment("instances_spawned")
    await backend.commit()


async def register_node(backend, node_id: str, coding_session_id: str, role: str, port: int) -> None:
    """Register this node in the cluster_nodes table.

    Args:
        backend: The async storage backend.
        node_id: Unique node identifier.
        coding_session_id: The coding session this node belongs to.
        role: Node role (leader or follower).
        port: The cluster/dashboard port.
    """
    from sylvan.database.orm import ClusterNode

    now = datetime.now(UTC).isoformat()
    await ClusterNode.create(
        node_id=node_id,
        pid=os.getpid(),
        role=role,
        ws_port=port if role == "leader" else None,
        connected_at=now,
        last_seen=now,
        coding_session_id=coding_session_id,
    )
    await backend.commit()


async def cleanup_dead_nodes(backend) -> int:
    """Remove cluster nodes whose PIDs are no longer alive.

    For each dead node's instances, merges stats into the parent coding
    session and marks the instance as ended. Purges instances older than
    7 days.

    Args:
        backend: The async storage backend.

    Returns:
        Number of nodes cleaned up.
    """
    from sylvan.database.orm import ClusterNode, CodingSession, Instance

    nodes = await ClusterNode.query().get()
    dead_count = 0
    affected_sessions: set[str] = set()

    for node in nodes:
        if _is_pid_alive(node.pid):
            continue

        now = datetime.now(UTC).isoformat()

        # Mark active instances for this node as ended
        active_instances = await Instance.where(node_id=node.node_id).where_null("ended_at").get()
        for inst in active_instances:
            await Instance.where(instance_id=inst.instance_id).update(ended_at=now)

            # Merge stats into coding session
            cs_id = inst.coding_session_id
            if cs_id:
                await CodingSession.where(id=cs_id).increment("total_tool_calls", inst.tool_calls or 0)
                await CodingSession.where(id=cs_id).increment("total_tokens_returned", inst.tokens_returned or 0)
                await CodingSession.where(id=cs_id).increment("total_tokens_avoided", inst.tokens_avoided or 0)
                await CodingSession.where(id=cs_id).increment(
                    "total_efficiency_returned", inst.efficiency_returned or 0
                )
                await CodingSession.where(id=cs_id).increment(
                    "total_efficiency_equivalent", inst.efficiency_equivalent or 0
                )
                await CodingSession.where(id=cs_id).increment("total_symbols_retrieved", inst.symbols_retrieved or 0)
                await CodingSession.where(id=cs_id).increment("total_sections_retrieved", inst.sections_retrieved or 0)
                await CodingSession.where(id=cs_id).increment("total_queries", inst.queries or 0)
                affected_sessions.add(cs_id)

        # Remove the dead node
        await ClusterNode.where(node_id=node.node_id).delete()
        dead_count += 1

    # Close coding sessions where all nodes are gone
    for cs_id in affected_sessions:
        remaining = await ClusterNode.where(coding_session_id=cs_id).exists()
        if not remaining:
            now = datetime.now(UTC).isoformat()
            await CodingSession.where(id=cs_id).where_null("ended_at").update(ended_at=now)

    # Purge instances older than 7 days
    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    purged = await Instance.where_not_null("ended_at").where("ended_at", "<", cutoff).delete()
    if purged:
        logger.debug("old_instances_purged", cutoff=cutoff)

    if dead_count or purged:
        await backend.commit()
    if dead_count:
        logger.info("dead_nodes_cleaned", count=dead_count)

    return dead_count


async def flush_instance_to_db(backend, session_tracker, cache, node_id: str, coding_session_id: str) -> None:
    """Persist current instance stats to the instances table using the ORM.

    Uses upsert (first_or_create pattern) to either create or update
    the instance row for this node.

    Args:
        backend: The async storage backend.
        session_tracker: The SessionTracker instance.
        cache: The QueryCache instance.
        node_id: Unique node identifier.
        coding_session_id: The coding session this instance belongs to.
    """
    from sylvan.database.orm import ClusterNode, Instance

    stats = session_tracker.get_session_stats()
    efficiency = session_tracker.get_efficiency_stats()
    cache_stats = cache.stats()
    now = datetime.now(UTC).isoformat()

    # Update node last_seen
    await ClusterNode.where(node_id=node_id).update(last_seen=now)

    # Update or create instance stats
    instance = await Instance.where(node_id=node_id).where_null("ended_at").first()
    if instance is None:
        await Instance.create(
            instance_id=node_id,
            node_id=node_id,
            coding_session_id=coding_session_id,
            started_at=stats.get("start_time", now),
            tool_calls=stats.get("tool_calls", 0),
            tokens_returned=stats.get("tokens_returned", 0),
            tokens_avoided=stats.get("tokens_avoided", 0),
            efficiency_returned=efficiency.get("total_returned", 0),
            efficiency_equivalent=efficiency.get("total_equivalent", 0),
            symbols_retrieved=stats.get("symbols_retrieved", 0),
            sections_retrieved=stats.get("sections_retrieved", 0),
            queries=stats.get("queries", 0),
            cache_hits=cache_stats.get("hits", 0),
            cache_misses=cache_stats.get("misses", 0),
            category_data=efficiency.get("by_category", {}),
        )
    else:
        await instance.update(
            tool_calls=stats.get("tool_calls", 0),
            tokens_returned=stats.get("tokens_returned", 0),
            tokens_avoided=stats.get("tokens_avoided", 0),
            efficiency_returned=efficiency.get("total_returned", 0),
            efficiency_equivalent=efficiency.get("total_equivalent", 0),
            symbols_retrieved=stats.get("symbols_retrieved", 0),
            sections_retrieved=stats.get("sections_retrieved", 0),
            queries=stats.get("queries", 0),
            cache_hits=cache_stats.get("hits", 0),
            cache_misses=cache_stats.get("misses", 0),
            category_data=efficiency.get("by_category", {}),
        )
    await backend.commit()

    state = get_cluster_state()
    if state.is_leader:
        from sylvan.database.orm import ClusterLock

        await ClusterLock.refresh(node_id)
        await backend.commit()

    from sylvan.events import emit

    cluster_data = {
        "role": state.role,
        "session_id": state.session_id,
        "coding_session_id": state.coding_session_id,
    }

    combined_efficiency = efficiency
    coding_history: list = []
    cluster_sessions: list = []

    if state.is_leader:
        try:
            from sylvan.dashboard.app import (
                _combine_session_efficiency,
                _get_cluster_sessions,
                _get_coding_session_history,
            )

            cluster_sessions = await _get_cluster_sessions()
            cluster_data["nodes"] = cluster_sessions
            cluster_data["active_count"] = sum(1 for s in cluster_sessions if s.get("alive"))
            cluster_data["total_tool_calls"] = sum(s.get("tool_calls", 0) for s in cluster_sessions)
            coding_history = await _get_coding_session_history(limit=10)

            combined = _combine_session_efficiency(cluster_sessions)
            if combined:
                combined_efficiency = combined
        except Exception:
            cluster_sessions = []
            coding_history = []

    from sylvan.database.orm import CodingSession

    cs = await CodingSession.where(id=coding_session_id).first()
    if cs:
        total_calls = cluster_data.get("total_tool_calls", stats.get("tool_calls", 0))
        total_ret = combined_efficiency.get("total_returned", 0)
        total_eq = combined_efficiency.get("total_equivalent", 0)
        await cs.update(
            total_tool_calls=total_calls,
            total_efficiency_returned=total_ret,
            total_efficiency_equivalent=total_eq,
        )
        await backend.commit()

    emit(
        "stats_update",
        {
            "session": stats,
            "efficiency": combined_efficiency,
            "cache": cache_stats,
            "cluster": cluster_data,
            "coding_history": coding_history,
        },
    )


async def _try_promote(backend, node_id: str, coding_session_id: str) -> None:
    """Check if the leader is dead and try to claim leadership.

    Args:
        backend: The async storage backend.
        node_id: This node's identifier.
        coding_session_id: The coding session ID.
    """
    from sylvan.config import get_config
    from sylvan.database.orm import ClusterLock, ClusterNode

    holder = await ClusterLock.holder()
    logger.debug(
        "try_promote_check",
        node_id=node_id,
        holder=holder.holder_id if holder else None,
        holder_pid=holder.pid if holder else None,
    )

    if holder is not None and holder.holder_id == node_id:
        return

    if holder is not None and _is_pid_alive(holder.pid or 0):
        logger.debug("try_promote_leader_alive", holder_pid=holder.pid)
        return

    cfg = get_config()

    if hasattr(backend, "promote_to_leader"):
        await backend.promote_to_leader()

    claimed = await ClusterLock.claim(node_id, os.getpid(), stale_seconds=cfg.cluster.lock_stale_threshold)
    logger.debug("try_promote_claim_result", claimed=claimed, node_id=node_id)
    if not claimed:
        if hasattr(backend, "enable_follower_mode"):
            await backend.enable_follower_mode()
        return

    logger.info("promoting_to_leader", node_id=node_id)

    from sylvan.cluster.state import ClusterState, set_cluster_state

    set_cluster_state(
        ClusterState(
            role="leader",
            session_id=node_id,
            coding_session_id=coding_session_id,
            leader_url=None,
        )
    )

    existing = await ClusterNode.where(node_id=node_id).first()
    now = datetime.now(UTC).isoformat()
    if existing:
        await ClusterNode.where(node_id=node_id).update(role="leader", ws_port=cfg.cluster.port)
    else:
        await ClusterNode.create(
            node_id=node_id,
            pid=os.getpid(),
            role="leader",
            ws_port=cfg.cluster.port,
            connected_at=now,
            last_seen=now,
            coding_session_id=coding_session_id,
        )
    await backend.commit()

    try:
        from sylvan.cluster.websocket import stop_follower_connection

        await stop_follower_connection()
    except Exception as exc:
        logger.debug("follower_ws_stop_on_promote_failed", error=str(exc))

    try:
        from sylvan.dashboard.server import start_dashboard

        await start_dashboard()
    except Exception as exc:
        logger.debug("dashboard_start_on_promote_failed", error=str(exc))

    try:
        from sylvan.cluster.websocket import start_leader_pings

        await start_leader_pings(interval=cfg.cluster.ws_ping_interval)
    except Exception as exc:
        logger.debug("leader_pings_on_promote_failed", error=str(exc))

    logger.info("promoted_to_leader", node_id=node_id)


async def _send_stats_to_leader(session_tracker, cache, node_id: str) -> None:
    """Send this follower's session stats to the leader via WebSocket.

    The leader uses this to update the follower's instance row in the DB,
    so cluster-wide stats are accurate.

    Args:
        session_tracker: The SessionTracker instance.
        cache: The QueryCache instance.
        node_id: This follower's node identifier.
    """
    try:
        from sylvan.cluster.websocket import _follower_ws

        if _follower_ws is None:
            return

        from sylvan.cluster import protocol

        stats = session_tracker.get_session_stats()
        efficiency = session_tracker.get_efficiency_stats()
        cache_stats = cache.stats()

        await _follower_ws.send(protocol.stats_message(node_id, stats, efficiency, cache_stats))
    except Exception as exc:
        logger.debug("follower_stats_send_failed", error=str(exc))


async def start_heartbeat(
    backend,
    session_tracker,
    cache,
    node_id: str,
    coding_session_id: str,
    role: str,
    interval: int = 10,
) -> None:
    """Start the background heartbeat loop.

    Periodically flushes instance stats to the database. The role is
    read from ClusterState (single source of truth), not tracked locally.

    Args:
        backend: The async storage backend.
        session_tracker: The SessionTracker instance.
        cache: The QueryCache instance.
        node_id: Unique node identifier.
        coding_session_id: The coding session this instance belongs to.
        role: Initial role (only used for first log message).
        interval: Seconds between heartbeat flushes.
    """

    async def _loop():
        while True:
            try:
                state = get_cluster_state()
                if state.is_leader:
                    await flush_instance_to_db(backend, session_tracker, cache, node_id, coding_session_id)
                    await cleanup_dead_nodes(backend)
                else:
                    await _try_promote(backend, node_id, coding_session_id)
                    await _send_stats_to_leader(session_tracker, cache, node_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("heartbeat_error", error=str(exc))
            await asyncio.sleep(interval)

    from sylvan.server.lifecycle import get_lifecycle

    lifecycle = get_lifecycle()
    if lifecycle:
        lifecycle.spawn(_loop(), name="heartbeat")
    else:
        asyncio.ensure_future(_loop())
