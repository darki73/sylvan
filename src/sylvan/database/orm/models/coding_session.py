"""ORM model for coding sessions — persistent multi-instance session tracking."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import Column, JsonColumn
from sylvan.database.orm.primitives.relations import HasMany


class CodingSession(Model):
    """Represents a coding session that spans one or more server instances.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "coding_sessions"
    __primary_key__ = "id"

    id = Column(str, primary_key=True)
    """Session identifier (e.g., cs-20260322-211811)."""

    started_at = Column(str)
    """ISO timestamp when the coding session started."""

    ended_at = Column(str, nullable=True)
    """ISO timestamp when the last instance exited, or None if still active."""

    total_tool_calls = Column(int, default=0)
    """Cumulative tool calls merged from dead instances."""

    total_tokens_returned = Column(int, default=0)
    """Cumulative tokens returned merged from dead instances."""

    total_tokens_avoided = Column(int, default=0)
    """Cumulative tokens avoided merged from dead instances."""

    total_efficiency_returned = Column(int, default=0)
    """Cumulative efficiency returned tokens merged from dead instances."""

    total_efficiency_equivalent = Column(int, default=0)
    """Cumulative efficiency equivalent tokens merged from dead instances."""

    total_symbols_retrieved = Column(int, default=0)
    """Cumulative symbols retrieved merged from dead instances."""

    total_sections_retrieved = Column(int, default=0)
    """Cumulative sections retrieved merged from dead instances."""

    total_queries = Column(int, default=0)
    """Cumulative queries merged from dead instances."""

    instances_spawned = Column(int, default=0)
    """Total number of instances that joined this coding session."""

    category_data = JsonColumn(default_factory=dict)
    """Per-category efficiency breakdown as JSON."""

    instances = HasMany("Instance", foreign_key="coding_session_id")
    """Instances belonging to this coding session."""
