"""Workspace model -- grouped repositories."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column
from sylvan.database.orm.primitives.relations import BelongsToMany


class Workspace(Model):
    """Represents a named grouping of repositories.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "workspaces"

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    name = Column(str)
    """Unique workspace name."""

    created_at = Column(str, nullable=True)
    """ISO timestamp of workspace creation."""

    description = Column(str, nullable=True)
    """Optional description of the workspace."""

    repos = BelongsToMany(
        "Repo",
        pivot_table="workspace_repos",
        foreign_key="workspace_id",
        related_key="repo_id",
    )
    """Repositories belonging to this workspace (many-to-many)."""
