"""Quality model -- code quality metrics per symbol."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import Column


class Quality(Model):
    """Stores code quality metrics for a symbol.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "quality"

    symbol_id = Column(str, primary_key=True)
    """Symbol ID serving as the primary key."""

    has_tests = Column(bool, default=False)
    """Whether the symbol has associated tests."""

    has_docs = Column(bool, default=False)
    """Whether the symbol has documentation."""

    has_types = Column(bool, default=False)
    """Whether the symbol has type annotations."""

    complexity = Column(int, default=0)
    """Cyclomatic complexity score."""

    change_frequency = Column(int, default=0)
    """Number of times this symbol has been changed in git history."""

    last_changed = Column(str, nullable=True)
    """ISO timestamp of the last git change."""
