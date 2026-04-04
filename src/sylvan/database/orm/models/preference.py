"""Preference model -- agent behavioral instructions with scope hierarchy."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column


class Preference(Model):
    """A key-value behavioral instruction with scope hierarchy.

    Three scopes: global (all repos), workspace, repo.
    Repo overrides workspace overrides global for the same key.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "preferences"

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    scope = Column(str)
    """Scope level: 'global', 'workspace', or 'repo'."""

    scope_id = Column(int, nullable=True)
    """Target ID: repo_id, workspace_id, or NULL for global."""

    key = Column(str)
    """Descriptive preference key (e.g. 'test_style', 'commit_format')."""

    instruction = Column(str)
    """Actionable instruction for the agent."""

    created_at = Column(str, nullable=True)
    """ISO timestamp of creation."""

    updated_at = Column(str, nullable=True)
    """ISO timestamp of last update."""
