"""Section model -- documentation sections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column, JsonColumn
from sylvan.database.orm.primitives.relations import BelongsTo, HasMany
from sylvan.database.orm.primitives.scopes import scope

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder


class Section(Model):
    """Represents a documentation section extracted from a file.

    Attributes:
        __table__: Database table name.
        __fts_table__: FTS5 virtual table for full-text search over sections.
        __fts_weights__: BM25 weight string for FTS5 ranking columns.
        __vec_table__: sqlite-vec virtual table for vector similarity search.
        __vec_column__: Column used to join with the vector table.
    """

    __table__ = "sections"
    __fts_table__ = "sections_fts"
    __fts_weights__ = "0, 10.0, 3.0, 2.0, 1.0"
    __vec_table__ = "sections_vec"
    __vec_column__ = "section_id"

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    file_id = Column(int)
    """Foreign key to the files table."""

    section_id = Column(str)
    """Stable unique identifier: 'repo::path::slug#level'."""

    title = Column(str)
    """Section heading text."""

    level = Column(int)
    """Heading level (1 for h1, 2 for h2, etc.)."""

    parent_section_id = Column(str, nullable=True)
    """Parent section ID for nested sections."""

    byte_start = Column(int)
    """Byte offset of section start in the file content blob."""

    byte_end = Column(int)
    """Byte offset of section end in the file content blob."""

    summary = Column(str, nullable=True)
    """AI-generated or heuristic summary."""

    tags = JsonColumn(list)
    """List of tags extracted from the section."""

    references = JsonColumn(list, column_name="refs")
    """List of cross-references found in the section."""

    content_hash = Column(str, nullable=True)
    """Hash of the section content for change detection."""

    body_text = Column(str, nullable=True)
    """First 500 chars of section body for FTS indexing."""

    file = BelongsTo("FileRecord", foreign_key="file_id")
    """Parent file record."""

    parent_section = BelongsTo("Section", foreign_key="parent_section_id", local_key="section_id")
    """Parent section for nested headings."""

    children = HasMany("Section", foreign_key="parent_section_id", local_key="section_id")
    """Child sections under this heading."""

    @scope
    def in_repo(query, name) -> QueryBuilder:
        """Filter to sections within a named repository."""
        return (
            query.join("files", "files.id = sections.file_id")
            .join("repos", "repos.id = files.repo_id")
            .where("repos.name", name)
        )

    @scope
    def in_doc(query, path) -> QueryBuilder:
        """Filter to sections within a specific document path."""
        return query.join("files", "files.id = sections.file_id").where("files.path", path)

    async def get_content(self) -> str:
        """Extract section content from blob via byte range.

        Returns:
            The section content string, or empty string if unavailable.
        """
        await self.load("file")
        file_rec = self.file
        if file_rec is None:
            return ""
        blob = await file_rec.get_content()
        if blob is None:
            return ""
        return blob[self.byte_start : self.byte_end].decode("utf-8", errors="replace")

    async def _resolve_file_path(self) -> str:
        """Resolve the file path via the file relation.

        Returns:
            The file path string, or empty string if unavailable.
        """
        await self.load("file")
        file_record = self.file
        return file_record.path if file_record else ""

    async def _resolve_repo_name(self) -> str:
        """Resolve the repo name via file -> repo relations.

        Returns:
            The repo name string, or empty string if unavailable.
        """
        await self.load("file")
        file_record = self.file
        if file_record is None:
            return ""
        await file_record.load("repo")
        repo = file_record.repo
        return repo.name if repo else ""

    async def to_summary_dict(self, *, include_repo: bool = False) -> dict:
        """Serialize to a summary dict for tool responses.

        Args:
            include_repo: Whether to include the repository name.

        Returns:
            A dict with section metadata suitable for API responses.
        """
        result = {
            "section_id": self.section_id,
            "title": self.title,
            "level": self.level,
            "summary": self.summary or "",
            "doc_path": await self._resolve_file_path(),
        }
        if include_repo:
            result["repo"] = await self._resolve_repo_name()
        return result
