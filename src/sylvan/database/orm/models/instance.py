"""ORM model for server instances -- stats-only observability snapshots."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import Column, JsonColumn
from sylvan.database.orm.primitives.relations import BelongsTo


class Instance(Model):
    """Stats snapshot for a server process instance.

    Pure observability - no cluster membership data. Cluster membership
    (pid, role, liveness) lives in ClusterNode.
    """

    __table__ = "instances"
    __primary_key__ = "instance_id"

    instance_id = Column(str, primary_key=True)
    """Unique instance identifier (hex string)."""

    node_id = Column(str)
    """The cluster node this instance ran on."""

    coding_session_id = Column(str)
    """Parent coding session ID."""

    started_at = Column(str)
    """ISO timestamp when the instance started."""

    ended_at = Column(str, nullable=True)
    """ISO timestamp when the instance exited, or None if alive."""

    tool_calls = Column(int, default=0)
    """Tool calls handled by this instance."""

    tokens_returned = Column(int, default=0)
    """Tokens returned to the agent by this instance."""

    tokens_avoided = Column(int, default=0)
    """Tokens avoided (saved) by this instance."""

    efficiency_returned = Column(int, default=0)
    """Efficiency metric: tokens returned."""

    efficiency_equivalent = Column(int, default=0)
    """Efficiency metric: equivalent full-file tokens."""

    symbols_retrieved = Column(int, default=0)
    """Symbols retrieved by this instance."""

    sections_retrieved = Column(int, default=0)
    """Sections retrieved by this instance."""

    queries = Column(int, default=0)
    """Search queries executed by this instance."""

    cache_hits = Column(int, default=0)
    """Query cache hits."""

    cache_misses = Column(int, default=0)
    """Query cache misses."""

    category_data = JsonColumn(default_factory=dict)
    """Per-category efficiency breakdown as JSON."""

    node = BelongsTo("ClusterNode", foreign_key="node_id")
    """The cluster node this instance ran on."""

    coding_session = BelongsTo("CodingSession", foreign_key="coding_session_id")
    """Parent coding session."""

    @classmethod
    def active(cls):
        """Scope: instances that haven't ended."""
        return cls.where_null("ended_at")

    @property
    def reduction_percent(self) -> float:
        """Token reduction percentage."""
        eq = self.efficiency_equivalent or 0
        ret = self.efficiency_returned or 0
        return round((1 - ret / eq) * 100, 1) if eq > 0 else 0.0
