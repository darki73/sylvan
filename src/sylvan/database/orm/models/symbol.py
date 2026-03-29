"""Symbol model -- code symbols (functions, classes, methods, etc.)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column, JsonColumn
from sylvan.database.orm.primitives.relations import BelongsTo, HasMany, HasOne
from sylvan.database.orm.primitives.scopes import scope

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder


class Symbol(Model):
    """Represents a code symbol extracted from source files.

    Attributes:
        __table__: Database table name.
        __fts_table__: FTS5 virtual table for full-text search over symbols.
        __fts_weights__: BM25 weight string for FTS5 ranking columns.
        __vec_table__: sqlite-vec virtual table for vector similarity search.
        __vec_column__: Column used to join with the vector table.
    """

    __table__ = "symbols"
    __fts_table__ = "symbols_fts"
    __fts_weights__ = "0, 10.0, 5.0, 3.0, 2.0, 2.0, 1.0"
    __vec_table__ = "symbols_vec"
    __vec_column__ = "symbol_id"

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    file_id = Column(int)
    """Foreign key to the files table."""

    symbol_id = Column(str)
    """Stable unique identifier: 'path::QualifiedName#kind'."""

    name = Column(str)
    """Short symbol name (e.g., 'parse_file')."""

    qualified_name = Column(str)
    """Fully qualified name including parent classes/modules."""

    kind = Column(str)
    """Symbol kind: function, class, method, constant, type, etc."""

    language = Column(str)
    """Programming language of the source file."""

    signature = Column(str, nullable=True)
    """Function/method signature string."""

    docstring = Column(str, nullable=True)
    """Extracted docstring text."""

    summary = Column(str, nullable=True)
    """AI-generated or heuristic summary."""

    decorators = JsonColumn(list)
    """List of decorator names applied to this symbol."""

    keywords = JsonColumn(list)
    """Extracted keywords for search boosting."""

    parent_symbol_id = Column(str, nullable=True)
    """Parent symbol ID for nested symbols (methods inside classes)."""

    line_start = Column(int, nullable=True)
    """Starting line number in the source file."""

    line_end = Column(int, nullable=True)
    """Ending line number in the source file."""

    byte_offset = Column(int)
    """Byte offset into the file content blob."""

    byte_length = Column(int)
    """Byte length of this symbol's source in the blob."""

    content_hash = Column(str, nullable=True)
    """Hash of the symbol's source content for change detection."""

    file = BelongsTo("FileRecord", foreign_key="file_id")
    """Parent file record."""

    children = HasMany("Symbol", foreign_key="parent_symbol_id", local_key="symbol_id")
    """Child symbols (e.g., methods inside a class)."""

    parent_symbol = BelongsTo("Symbol", foreign_key="parent_symbol_id", local_key="symbol_id")
    """Parent symbol for nested symbols."""

    references = HasMany("Reference", foreign_key="source_symbol_id", local_key="symbol_id", on_delete="cascade")
    """Outgoing references from this symbol."""

    quality_info = HasOne("Quality", foreign_key="symbol_id", local_key="symbol_id", on_delete="cascade")
    """Associated quality metrics."""

    @scope
    def functions(query) -> QueryBuilder:
        """Filter to function symbols only."""
        return query.where(kind="function")

    @scope
    def methods(query) -> QueryBuilder:
        """Filter to method symbols only."""
        return query.where(kind="method")

    @scope
    def classes(query) -> QueryBuilder:
        """Filter to class symbols only."""
        return query.where(kind="class")

    @scope
    def constants(query) -> QueryBuilder:
        """Filter to constant symbols only."""
        return query.where(kind="constant")

    @scope
    def types(query) -> QueryBuilder:
        """Filter to type symbols only."""
        return query.where(kind="type")

    @scope
    def in_repo(query, name) -> QueryBuilder:
        """Filter to symbols within a named repository."""
        return (
            query.join("files", "files.id = symbols.file_id")
            .join("repos", "repos.id = files.repo_id")
            .where("repos.name", name)
        )

    @scope
    def in_workspace(query, name) -> QueryBuilder:
        """Filter to symbols within a named workspace."""
        return (
            query.join("files", "files.id = symbols.file_id")
            .join("workspace_repos", "workspace_repos.repo_id = files.repo_id")
            .join("workspaces", "workspaces.id = workspace_repos.workspace_id")
            .where("workspaces.name", name)
        )

    @scope
    def in_file(query, path) -> QueryBuilder:
        """Filter to symbols within a specific file path."""
        return query.join("files", "files.id = symbols.file_id").where("files.path", path)

    async def get_source(self) -> str:
        """Extract source code from blob via byte offset.

        Returns:
            The source code string for this symbol, or empty string if unavailable.
        """
        await self.load("file")
        file_rec = self.file
        if file_rec is None:
            return ""
        content = await file_rec.get_content()
        if content is None:
            return ""
        return content[self.byte_offset : self.byte_offset + self.byte_length].decode("utf-8", errors="replace")

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
            A dict with symbol metadata suitable for API responses.
        """
        result = {
            "symbol_id": self.symbol_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "language": self.language,
            "file": await self._resolve_file_path(),
            "signature": self.signature or "",
            "summary": self.summary or "",
            "line_start": self.line_start,
            "line_end": self.line_end,
        }
        if include_repo:
            result["repo"] = await self._resolve_repo_name()
        return result

    async def to_detail_dict(self) -> dict:
        """Serialize to a full detail dict including source code.

        Returns:
            A dict with complete symbol data including source and docstring.
        """
        result = await self.to_summary_dict()
        result["docstring"] = self.docstring or ""
        result["decorators"] = self.decorators or []
        result["source"] = await self.get_source()
        return result
