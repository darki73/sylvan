"""UsageStats model -- per-repo per-day usage metrics.

Note: The DB schema uses a composite PRIMARY KEY (repo_id, date).
The ORM does not support composite PKs natively, so we use repo_id
as the PK column for basic ORM operations. Full CRUD on this model
should use raw SQL for correctness.
"""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import Column


class UsageStats(Model):
    """Tracks per-repo per-day usage metrics across sessions.

    Attributes:
        __table__: Database table name.
        _pk_column: Primary key column (best-effort for composite key table).
    """

    __table__ = "usage_stats"
    _pk_column = "repo_id"  # Best-effort PK for composite key table

    repo_id = Column(int)
    """Foreign key to the repos table."""

    date = Column(str)
    """ISO date string (YYYY-MM-DD) for this stats row."""

    sessions = Column(int, default=0)
    """Number of sessions that accessed this repo on this date."""

    tool_calls = Column(int, default=0)
    """Total tool calls against this repo on this date."""

    tokens_returned = Column(int, default=0)
    """Total tokens returned in responses."""

    tokens_avoided = Column(int, default=0)
    """Estimated tokens saved by using summaries instead of full content."""

    symbols_retrieved = Column(int, default=0)
    """Number of symbols retrieved."""

    sections_retrieved = Column(int, default=0)
    """Number of sections retrieved."""
