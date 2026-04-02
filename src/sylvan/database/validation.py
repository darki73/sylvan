"""Data models for sylvan's SQLite-backed storage."""

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(slots=True)
class Repo:
    """Dataclass representation of a repository for validation and transfer.

    Attributes:
        id: Primary key, or None for unsaved instances.
        name: Human-readable repository name.
        source_path: Absolute path to the repository on disk.
        github_url: GitHub URL for the repository, if known.
        indexed_at: ISO timestamp of the last indexing run.
        git_head: Git HEAD commit hash at the time of indexing.
    """

    id: int | None = None
    name: str = ""
    source_path: str | None = None
    github_url: str | None = None
    indexed_at: str = ""
    git_head: str | None = None


@dataclass(slots=True)
class FileRecord:
    """Dataclass representation of a file record for validation and transfer.

    Attributes:
        id: Primary key, or None for unsaved instances.
        repo_id: Foreign key to the repos table.
        path: Relative file path within the repository.
        language: Detected programming language.
        content_hash: SHA-256 hash of the raw file content.
        byte_size: File size in bytes.
        mtime: File modification time as a Unix timestamp.
    """

    id: int | None = None
    repo_id: int = 0
    path: str = ""
    language: str | None = None
    content_hash: str = ""
    byte_size: int = 0
    mtime: float | None = None


@dataclass(slots=True)
class Symbol:
    """Dataclass representation of a code symbol for validation and transfer.

    Attributes:
        id: Primary key, or None for unsaved instances.
        file_id: Foreign key to the files table.
        symbol_id: Stable unique identifier: ``path::QualifiedName#kind``.
        name: Short symbol name.
        qualified_name: Fully qualified name including parent classes/modules.
        kind: Symbol kind (function, class, method, constant, type).
        language: Programming language of the source file.
        signature: Function/method signature string.
        docstring: Extracted docstring text.
        summary: AI-generated or heuristic summary.
        decorators: List of decorator names applied to this symbol.
        keywords: Extracted keywords for search boosting.
        parent_symbol_id: Parent symbol ID for nested symbols.
        line_start: Starting line number in the source file.
        line_end: Ending line number in the source file.
        byte_offset: Byte offset into the file content blob.
        byte_length: Byte length of this symbol's source in the blob.
        content_hash: Hash of the symbol's source content for change detection.
    """

    id: int | None = None
    file_id: int = 0
    symbol_id: str = ""
    name: str = ""
    qualified_name: str = ""
    kind: str = ""  # function, class, method, constant, type
    language: str = ""
    signature: str | None = None
    docstring: str | None = None
    summary: str | None = None
    decorators: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    parent_symbol_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    byte_offset: int = 0
    byte_length: int = 0
    content_hash: str | None = None
    cyclomatic: int = 0
    max_nesting: int = 0
    param_count: int = 0


class SymbolKind(StrEnum):
    """Recognized symbol kind values."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    CONSTANT = "constant"
    TYPE = "type"
    TEMPLATE = "template"
    IMPORT = "import"


VALID_SYMBOL_KINDS = frozenset(SymbolKind)
"""Frozenset of all :class:`SymbolKind` values for membership checks."""


def make_symbol_id(file_path: str, qualified_name: str, kind: str = "") -> str:
    """Build a stable symbol ID: ``path::QualifiedName#kind``.

    Args:
        file_path: Relative path to the file containing the symbol.
        qualified_name: Fully qualified name of the symbol.
        kind: Optional symbol kind suffix.

    Returns:
        A stable, unique symbol identifier string.
    """
    sid = f"{file_path}::{qualified_name}"
    if kind:
        sid += f"#{kind}"
    return sid


@dataclass(slots=True)
class Section:
    """Dataclass representation of a documentation section for validation and transfer.

    Attributes:
        id: Primary key, or None for unsaved instances.
        file_id: Foreign key to the files table.
        section_id: Stable unique identifier.
        title: Section heading text.
        level: Heading level (1 for h1, 2 for h2, etc.).
        parent_section_id: Parent section ID for nested sections.
        byte_start: Byte offset of section start in the file content blob.
        byte_end: Byte offset of section end in the file content blob.
        summary: AI-generated or heuristic summary.
        tags: List of tags extracted from the section.
        references: List of cross-references found in the section.
        content_hash: Hash of the section content for change detection.
    """

    id: int | None = None
    file_id: int = 0
    section_id: str = ""
    title: str = ""
    level: int = 0
    parent_section_id: str | None = None
    byte_start: int = 0
    byte_end: int = 0
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    content_hash: str | None = None


@dataclass(slots=True)
class FileImport:
    """Dataclass representation of a file import statement for validation and transfer.

    Attributes:
        id: Primary key, or None for unsaved instances.
        file_id: Foreign key to the files table.
        specifier: The import specifier (e.g., ``os.path`` or ``react``).
        names: List of imported names from the specifier.
        resolved_file_id: Foreign key to the resolved target file, if known.
    """

    id: int | None = None
    file_id: int = 0
    specifier: str = ""
    names: list[str] = field(default_factory=list)
    resolved_file_id: int | None = None
