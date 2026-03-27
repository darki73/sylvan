"""Cluster node model -- one row per live sylvan server process."""

from __future__ import annotations

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import Column
from sylvan.database.orm.primitives.relations import BelongsTo, HasMany


class ClusterNode(Model):
    """A live sylvan server process in the cluster.

    The leader writes all rows. Followers report their state over
    WebSocket and the leader persists it here.
    """

    __table__ = "cluster_nodes"
    __primary_key__ = "node_id"

    node_id = Column(str, primary_key=True)
    """Unique node identifier (hex string)."""

    pid = Column(int)
    """OS process ID."""

    role = Column(str, default="follower")
    """Node role: leader or follower."""

    ws_port = Column(int, nullable=True)
    """WebSocket port (leader only, followers connect to this)."""

    connected_at = Column(str)
    """ISO timestamp when this node joined the cluster."""

    last_seen = Column(str)
    """ISO timestamp of the last heartbeat or activity."""

    coding_session_id = Column(str)
    """Parent coding session ID."""

    coding_session = BelongsTo("CodingSession", foreign_key="coding_session_id")
    """Parent coding session."""

    instances = HasMany("Instance", foreign_key="node_id")
    """Stats snapshots for this node."""

    @classmethod
    def leader(cls):
        """Scope: the current leader node."""
        return cls.where(role="leader")

    @classmethod
    def followers(cls):
        """Scope: all follower nodes."""
        return cls.where(role="follower")
