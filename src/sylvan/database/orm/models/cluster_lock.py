"""Cluster lock model -- single-row table for leader election."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import Column


class ClusterLock(Model):
    """Single-row table for atomic leader election.

    Only one row ever exists. The leader refreshes ``heartbeat_at``
    periodically. Followers claim by updating the row when it is
    unclaimed, stale, or held by a dead process.
    """

    __table__ = "cluster_lock"
    __primary_key__ = "holder_id"

    holder_id = Column(str, nullable=True)
    """Node ID of the current leader, or None if unclaimed."""

    pid = Column(int, nullable=True)
    """OS process ID of the current leader."""

    claimed_at = Column(str, nullable=True)
    """ISO timestamp when leadership was claimed."""

    heartbeat_at = Column(str, nullable=True)
    """ISO timestamp of the last heartbeat from the leader."""

    @classmethod
    async def claim(cls, node_id: str, pid: int, stale_seconds: int = 10) -> bool:
        """Attempt to claim leadership.

        Succeeds if the lock is unclaimed, the heartbeat is stale, or
        the holder has no heartbeat. SQLite's write lock ensures only
        one caller wins.

        Args:
            node_id: The claiming node's unique identifier.
            pid: The claiming process's OS PID.
            stale_seconds: Seconds before a heartbeat is considered stale.

        Returns:
            True if this node is now the leader.
        """
        now = datetime.now(UTC).isoformat()
        stale = (datetime.now(UTC) - timedelta(seconds=stale_seconds)).isoformat()
        affected = (
            await cls.where_null("pid")
            .or_where_null("heartbeat_at")
            .or_where("heartbeat_at", "<", stale)
            .update(holder_id=node_id, pid=pid, claimed_at=now, heartbeat_at=now)
        )
        return affected > 0

    @classmethod
    async def release(cls) -> None:
        """Release the lock (graceful step-down)."""
        await cls.query().update(holder_id=None, pid=None, claimed_at=None, heartbeat_at=None)

    @classmethod
    async def refresh(cls, node_id: str) -> None:
        """Update the heartbeat timestamp (leader calls periodically).

        Args:
            node_id: The leader's node identifier.
        """
        now = datetime.now(UTC).isoformat()
        await cls.where(holder_id=node_id).update(heartbeat_at=now)

    @classmethod
    async def holder(cls) -> ClusterLock | None:
        """Get the current lock holder.

        Returns:
            The ClusterLock row if someone holds the lock, or None.
        """
        return await cls.where_not_null("holder_id").first()
