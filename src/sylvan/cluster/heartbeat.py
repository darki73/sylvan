"""Heartbeat -- node registration, stats persistence, dead instance cleanup."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

from sylvan.cluster.discovery import _is_pid_alive
from sylvan.cluster.state import get_cluster_state
from sylvan.logging import get_logger

logger = get_logger(__name__)

_heartbeat_task: asyncio.Task | None = None


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

    # Also refresh the cluster lock heartbeat if we're the leader
    state = get_cluster_state()
    if state.is_leader:
        from sylvan.database.orm import ClusterLock

        await ClusterLock.refresh(node_id)
        await backend.commit()


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
    global _heartbeat_task

    async def _loop():
        while True:
            try:
                state = get_cluster_state()
                if state.is_leader:
                    await flush_instance_to_db(backend, session_tracker, cache, node_id, coding_session_id)
                    await cleanup_dead_nodes(backend)
            except Exception as exc:
                logger.debug("heartbeat_error", error=str(exc))
            await asyncio.sleep(interval)

    _heartbeat_task = asyncio.ensure_future(_loop())


async def stop_heartbeat() -> None:
    """Cancel the heartbeat task."""
    global _heartbeat_task
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        _heartbeat_task = None


def stop_heartbeat_sync() -> None:
    """Cancel the heartbeat task (sync, for signal handlers)."""
    global _heartbeat_task
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        _heartbeat_task = None
