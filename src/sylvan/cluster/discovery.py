"""Cluster discovery -- determine leader/follower role on startup."""

import os
import uuid
from datetime import UTC, datetime

from sylvan.logging import get_logger

logger = get_logger(__name__)


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running.

    Uses OpenProcess on Windows (os.kill sends CtrlBreakEvent which
    would terminate the target process).

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists and is running.
    """
    import sys

    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False

    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def generate_node_id() -> str:
    """Generate a unique node identifier.

    Returns:
        A 12-character hex string.
    """
    return uuid.uuid4().hex[:12]


def generate_coding_session_id() -> str:
    """Generate a coding session identifier based on current time.

    Returns:
        A string like ``cs-20260327-193000``.
    """
    return f"cs-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


async def discover_role(stale_seconds: int = 10) -> tuple[str, str, str]:
    """Determine whether this instance should be leader or follower.

    Uses the ``cluster_lock`` table in the database for atomic election.
    If the lock is unclaimed or stale, this instance claims leadership.
    Otherwise, it reads the existing leader's info and becomes a follower.

    Args:
        stale_seconds: Seconds before a heartbeat is considered stale.

    Returns:
        Tuple of (role, node_id, coding_session_id).
        role is ``"leader"`` or ``"follower"``.
    """
    from sylvan.database.orm.models.cluster_lock import ClusterLock

    node_id = generate_node_id()
    pid = os.getpid()

    # Try to claim leadership
    claimed = await ClusterLock.claim(node_id, pid, stale_seconds=stale_seconds)

    if claimed:
        coding_session_id = generate_coding_session_id()
        logger.info("leader_mode", node_id=node_id, coding_session_id=coding_session_id)
        return "leader", node_id, coding_session_id

    # Someone else is leader - read their info
    holder = await ClusterLock.holder()
    if holder and holder.holder_id:
        # Join the existing leader's coding session
        from sylvan.database.orm.models.cluster_node import ClusterNode

        leader_node = await ClusterNode.where(node_id=holder.holder_id).first()
        if leader_node:
            coding_session_id = leader_node.coding_session_id or generate_coding_session_id()
        else:
            coding_session_id = generate_coding_session_id()

        logger.info(
            "follower_mode",
            node_id=node_id,
            leader_node=holder.holder_id,
            coding_session_id=coding_session_id,
        )
        return "follower", node_id, coding_session_id

    # Fallback: no holder found (shouldn't happen after claim attempt)
    coding_session_id = generate_coding_session_id()
    logger.warning("standalone_mode", node_id=node_id, coding_session_id=coding_session_id)
    return "leader", node_id, coding_session_id


async def release_leadership() -> None:
    """Release the cluster lock (graceful step-down).

    Called on shutdown to allow other instances to claim leadership.
    """
    from sylvan.database.orm.models.cluster_lock import ClusterLock

    await ClusterLock.release()
    logger.info("leadership_released")


def release_leadership_sync() -> None:
    """Release leadership synchronously (for signal handlers).

    Uses a fresh sync sqlite3 connection to release the lock since
    the event loop may be dead.
    """
    import sqlite3

    from sylvan.config import get_config

    try:
        config = get_config()
        conn = sqlite3.connect(str(config.db_path))
        conn.execute("UPDATE cluster_lock SET holder_id = NULL, pid = NULL, claimed_at = NULL, heartbeat_at = NULL")
        conn.commit()
        conn.close()
        logger.info("leadership_released_sync")
    except Exception as exc:
        logger.debug("leadership_release_sync_failed", error=str(exc))
