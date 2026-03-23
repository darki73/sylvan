"""Heartbeat -- persist instance stats and push to leader."""

import asyncio
import json
import os
from datetime import UTC, datetime

from sylvan.cluster.discovery import _is_pid_alive
from sylvan.cluster.state import get_cluster_state
from sylvan.logging import get_logger

logger = get_logger(__name__)

_heartbeat_task: asyncio.Task | None = None


async def ensure_coding_session(backend, coding_session_id: str) -> None:
    """Create the coding_sessions row if it doesn't exist, and increment instances_spawned.

    Args:
        backend: The async storage backend.
        coding_session_id: The coding session identifier.
    """
    now = datetime.now(UTC).isoformat()
    existing = await backend.fetch_one(
        "SELECT id FROM coding_sessions WHERE id = ?", [coding_session_id]
    )
    if existing is None:
        await backend.execute(
            "INSERT INTO coding_sessions (id, started_at, instances_spawned) VALUES (?, ?, 1)",
            [coding_session_id, now],
        )
    else:
        await backend.execute(
            "UPDATE coding_sessions SET instances_spawned = instances_spawned + 1 WHERE id = ?",
            [coding_session_id],
        )
    await backend.commit()


async def cleanup_dead_instances(backend) -> int:
    """Mark instances whose PIDs are no longer alive as ended.

    For each dead instance, merges its stats into the parent coding_sessions
    row and sets ``ended_at``. If all instances of a coding session are dead,
    also sets ``ended_at`` on the coding session.

    Args:
        backend: The async storage backend.

    Returns:
        Number of instances marked as dead.
    """
    rows = await backend.fetch_all(
        "SELECT instance_id, pid, coding_session_id, tool_calls, tokens_returned, "
        "tokens_avoided, efficiency_returned, efficiency_equivalent, "
        "symbols_retrieved, sections_retrieved, queries "
        "FROM instances WHERE ended_at IS NULL"
    )
    dead_count = 0
    affected_sessions: set[str] = set()

    for r in rows:
        if _is_pid_alive(r["pid"]):
            continue

        now = datetime.now(UTC).isoformat()
        instance_id = r["instance_id"]
        cs_id = r["coding_session_id"]

        # Mark instance as ended
        await backend.execute(
            "UPDATE instances SET ended_at = ? WHERE instance_id = ?",
            [now, instance_id],
        )

        # Merge stats into coding_sessions
        await backend.execute(
            """UPDATE coding_sessions SET
                total_tool_calls = total_tool_calls + ?,
                total_tokens_returned = total_tokens_returned + ?,
                total_tokens_avoided = total_tokens_avoided + ?,
                total_efficiency_returned = total_efficiency_returned + ?,
                total_efficiency_equivalent = total_efficiency_equivalent + ?,
                total_symbols_retrieved = total_symbols_retrieved + ?,
                total_sections_retrieved = total_sections_retrieved + ?,
                total_queries = total_queries + ?
            WHERE id = ?""",
            [
                r.get("tool_calls", 0) or 0,
                r.get("tokens_returned", 0) or 0,
                r.get("tokens_avoided", 0) or 0,
                r.get("efficiency_returned", 0) or 0,
                r.get("efficiency_equivalent", 0) or 0,
                r.get("symbols_retrieved", 0) or 0,
                r.get("sections_retrieved", 0) or 0,
                r.get("queries", 0) or 0,
                cs_id,
            ],
        )

        await backend.execute(
            "DELETE FROM instances WHERE instance_id = ?",
            [instance_id],
        )

        affected_sessions.add(cs_id)
        dead_count += 1

    for cs_id in affected_sessions:
        alive_row = await backend.fetch_one(
            "SELECT instance_id FROM instances WHERE coding_session_id = ? AND ended_at IS NULL",
            [cs_id],
        )
        if alive_row is None:
            now = datetime.now(UTC).isoformat()
            await backend.execute(
                "UPDATE coding_sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                [now, cs_id],
            )

    if dead_count:
        await backend.commit()
        logger.info("dead_instances_cleaned", count=dead_count)

    return dead_count


async def flush_instance_to_db(
    backend, session_tracker, cache, instance_id: str, coding_session_id: str, role: str
) -> None:
    """Persist current instance stats to the instances table.

    Args:
        backend: The async storage backend.
        session_tracker: The SessionTracker instance.
        cache: The QueryCache instance.
        instance_id: Unique instance identifier.
        coding_session_id: The coding session this instance belongs to.
        role: This instance's cluster role (``"leader"`` or ``"follower"``).
    """
    stats = session_tracker.get_session_stats()
    efficiency = session_tracker.get_efficiency_stats()
    cache_stats = cache.stats()

    now = datetime.now(UTC).isoformat()

    await backend.execute(
        """INSERT OR REPLACE INTO instances
           (instance_id, coding_session_id, pid, role, started_at, last_heartbeat,
            tool_calls, tokens_returned, tokens_avoided,
            efficiency_returned, efficiency_equivalent,
            symbols_retrieved, sections_retrieved, queries,
            cache_hits, cache_misses, category_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            instance_id,
            coding_session_id,
            os.getpid(),
            role,
            stats.get("start_time", now),
            now,
            stats.get("tool_calls", 0),
            stats.get("tokens_returned", 0),
            stats.get("tokens_avoided", 0),
            efficiency.get("total_returned", 0),
            efficiency.get("total_equivalent", 0),
            stats.get("symbols_retrieved", 0),
            stats.get("sections_retrieved", 0),
            stats.get("queries", 0),
            cache_stats.get("hits", 0),
            cache_stats.get("misses", 0),
            json.dumps(efficiency.get("by_category", {})),
        ],
    )
    await backend.commit()


async def push_stats_to_leader(session_tracker, cache, instance_id: str) -> None:
    """Push instance stats to leader over HTTP (follower only).

    Args:
        session_tracker: The SessionTracker instance.
        cache: The QueryCache instance.
        instance_id: Unique instance identifier.
    """
    import httpx

    state = get_cluster_state()
    if not state.leader_url:
        return

    stats = session_tracker.get_session_stats()
    efficiency = session_tracker.get_efficiency_stats()
    cache_stats = cache.stats()

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{state.leader_url}/api/session/heartbeat", json={
                "session_id": instance_id,
                "stats": stats,
                "efficiency": efficiency,
                "cache": cache_stats,
            })
    except Exception as exc:
        logger.debug("heartbeat_push_failed", error=str(exc))


async def start_heartbeat(
    backend, session_tracker, cache, instance_id: str, coding_session_id: str, role: str, interval: int = 10
) -> None:
    """Start the background heartbeat loop.

    Periodically flushes instance stats to the database and, if running
    as a follower, pushes stats to the leader over HTTP.

    Args:
        backend: The async storage backend.
        session_tracker: The SessionTracker instance.
        cache: The QueryCache instance.
        instance_id: Unique instance identifier.
        coding_session_id: The coding session this instance belongs to.
        role: This instance's cluster role.
        interval: Seconds between heartbeat flushes.
    """
    global _heartbeat_task

    current_role = role

    async def _loop():
        nonlocal current_role
        while True:
            try:
                await flush_instance_to_db(backend, session_tracker, cache, instance_id, coding_session_id, current_role)
                if current_role == "follower":
                    await push_stats_to_leader(session_tracker, cache, instance_id)
                    if await _should_promote():
                        current_role = "leader"
                        await _promote_to_leader(backend, instance_id, coding_session_id)
            except Exception as exc:
                logger.debug("heartbeat_error", error=str(exc))
            await asyncio.sleep(interval)

    _heartbeat_task = asyncio.ensure_future(_loop())


async def _should_promote() -> bool:
    """Check if the leader is dead and this follower should promote.

    Returns:
        True if leader PID is no longer alive.
    """
    from sylvan.cluster.discovery import _LEADER_FILE, _is_pid_alive

    if not _LEADER_FILE.exists():
        return True
    try:
        data = json.loads(_LEADER_FILE.read_text())
        leader_pid = data.get("pid")
        return not (leader_pid and _is_pid_alive(leader_pid))
    except (json.JSONDecodeError, OSError):
        return True


async def _promote_to_leader(backend: object, instance_id: str, coding_session_id: str) -> None:
    """Promote this follower to leader.

    Claims the leader file, starts the dashboard, and updates cluster state.

    Args:
        backend: The async storage backend.
        instance_id: This instance's identifier.
        coding_session_id: The coding session ID.
    """
    import os

    from sylvan.cluster.discovery import _LEADER_FILE
    from sylvan.cluster.state import ClusterState, set_cluster_state
    from sylvan.config import get_config

    cfg = get_config()
    port = cfg.cluster.port

    leader_data = {
        "pid": os.getpid(),
        "session_id": instance_id,
        "coding_session_id": coding_session_id,
        "started_at": datetime.now(UTC).isoformat(),
        "http_port": port,
    }
    _LEADER_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LEADER_FILE.write_text(json.dumps(leader_data, indent=2))

    set_cluster_state(ClusterState(
        role="leader",
        session_id=instance_id,
        coding_session_id=coding_session_id,
        leader_url=None,
    ))

    try:
        from sylvan.dashboard.server import start_dashboard
        await start_dashboard()
    except Exception as exc:
        logger.debug("dashboard_start_on_promote_failed", error=str(exc))

    logger.info("promoted_to_leader", instance_id=instance_id, port=port)


async def stop_heartbeat() -> None:
    """Cancel the heartbeat task."""
    global _heartbeat_task
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        _heartbeat_task = None
