"""Repo model -- indexed repositories and libraries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column
from sylvan.database.orm.primitives.relations import BelongsToMany, HasMany
from sylvan.database.orm.primitives.scopes import scope

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder


class Repo(Model):
    """Represents an indexed repository or third-party library.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "repos"

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    name = Column(str)
    """Human-readable repository name."""

    source_path = Column(str, nullable=True)
    """Absolute path to the repository on disk."""

    github_url = Column(str, nullable=True)
    """GitHub URL for the repository, if known."""

    indexed_at = Column(str)
    """ISO timestamp of the last indexing run."""

    git_head = Column(str, nullable=True)
    """Git HEAD commit hash at the time of indexing."""

    repo_type = Column(str, default="local")  # "local" | "library"
    """Whether this is a local repo or an indexed third-party library."""

    package_manager = Column(str, nullable=True)  # "pip" | "npm" | "cargo" | "go"
    """Package manager ecosystem for library repos."""

    package_name = Column(str, nullable=True)
    """Package name within the ecosystem."""

    version = Column(str, nullable=True)
    """Version string for library repos."""

    files = HasMany("FileRecord", foreign_key="repo_id", on_delete="cascade")
    """Files belonging to this repository."""

    usage_stats = HasMany("UsageStats", foreign_key="repo_id", on_delete="cascade")
    """Usage statistics for this repository."""

    workspaces = BelongsToMany(
        "Workspace",
        pivot_table="workspace_repos",
        foreign_key="repo_id",
        related_key="workspace_id",
        on_delete="detach",
    )
    """Workspaces this repository belongs to (many-to-many)."""

    @scope
    def libraries(query) -> QueryBuilder:
        """Filter to library-type repositories."""
        return query.where(repo_type="library")

    @scope
    def local_repos(query) -> QueryBuilder:
        """Filter to locally indexed repositories."""
        return query.where(repo_type="local")
