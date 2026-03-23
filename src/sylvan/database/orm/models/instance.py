"""ORM model for server instances — ephemeral per-process tracking."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import Column, JsonColumn
from sylvan.database.orm.primitives.relations import BelongsTo


class Instance(Model):
    """Represents a single sylvan server process instance.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "instances"
    __primary_key__ = "instance_id"

    instance_id = Column(str, primary_key=True)
    """Unique instance identifier (hex string)."""

    coding_session_id = Column(str)
    """Parent coding session ID."""

    pid = Column(int)
    """OS process ID."""

    role = Column(str, default="leader")
    """Instance role: leader or follower."""

    started_at = Column(str)
    """ISO timestamp when the instance started."""

    ended_at = Column(str, nullable=True)
    """ISO timestamp when the instance exited, or None if alive."""

    last_heartbeat = Column(str)
    """ISO timestamp of the last heartbeat write."""

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

    coding_session = BelongsTo("CodingSession", foreign_key="coding_session_id")
    """Parent coding session."""
