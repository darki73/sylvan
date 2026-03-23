"""Cluster state -- global singleton for the current instance's role."""

from dataclasses import dataclass


@dataclass
class ClusterState:
    """Tracks this instance's role in the cluster.

    Attributes:
        role: Either ``"leader"`` or ``"follower"``.
        session_id: Unique identifier for this instance.
        coding_session_id: Identifier for the coding session this instance belongs to.
        leader_url: HTTP URL of the leader (for followers to proxy writes).
    """

    role: str = "leader"
    session_id: str = ""
    coding_session_id: str = ""
    leader_url: str | None = None

    @property
    def is_leader(self) -> bool:
        """Check if this instance is the cluster leader.

        Returns:
            True if this instance owns writes and runs the dashboard.
        """
        return self.role == "leader"

    @property
    def is_follower(self) -> bool:
        """Check if this instance is a cluster follower.

        Returns:
            True if this instance proxies writes to the leader.
        """
        return self.role == "follower"


_state: ClusterState | None = None


def get_cluster_state() -> ClusterState:
    """Get the global cluster state singleton.

    Returns:
        The shared ClusterState instance, created with defaults if needed.
    """
    global _state
    if _state is None:
        _state = ClusterState()
    return _state


def set_cluster_state(state: ClusterState) -> None:
    """Replace the global cluster state singleton.

    Args:
        state: The new ClusterState to install.
    """
    global _state
    _state = state
