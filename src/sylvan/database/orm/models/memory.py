"""Memory model -- agent project knowledge with vector search."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column, JsonColumn
from sylvan.database.orm.primitives.relations import BelongsTo


class Memory(Model):
    """A stored agent insight, decision, or context for a repository.

    Attributes:
        __table__: Database table name.
        __vec_table__: sqlite-vec virtual table for similarity search.
        __vec_column__: Column used to join with the vector table.
    """

    __table__ = "memories"
    __vec_table__ = "memories_vec"
    __vec_column__ = "memory_id"

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    repo_id = Column(int)
    """Foreign key to the repository this memory belongs to."""

    content = Column(str)
    """The memory content - insight, decision, or context."""

    tags = JsonColumn(list)
    """Tags for categorization."""

    created_at = Column(str, nullable=True)
    """ISO timestamp of creation."""

    updated_at = Column(str, nullable=True)
    """ISO timestamp of last update."""

    repo = BelongsTo("Repo", foreign_key="repo_id")
    """Repository this memory belongs to."""
