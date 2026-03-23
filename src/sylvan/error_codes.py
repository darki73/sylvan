"""Typed exception hierarchy for structured error responses.

All sylvan errors inherit from :class:`SylvanError`, carry a machine-readable
``code``, and serialize to dicts suitable for MCP tool responses via
:meth:`SylvanError.to_dict`.

Backward-compatible constructor functions (``symbol_not_found()``, etc.) are
retained at module level so that un-migrated code and existing tests continue
to work.  New code should ``raise SymbolNotFoundError(...)`` instead.
"""

from __future__ import annotations

from typing import Any


class SylvanError(Exception):
    """Base exception for all sylvan errors.

    All sylvan exceptions carry a machine-readable error code and
    convert to structured dicts for MCP tool responses.

    Attributes:
        code: Machine-readable error code (e.g. ``symbol_not_found``).
        detail: Human-readable error message.
        context: Arbitrary key-value pairs included in the serialized dict.
    """

    code: str = "internal_error"

    def __init__(self, detail: str = "", *, _meta: dict[str, Any] | None = None, **context: object) -> None:
        """Initialize a sylvan error.

        Args:
            detail: Human-readable description of what went wrong.
            _meta: Optional response-envelope metadata (timing, diagnostics).
                When present, ``to_dict`` includes it as ``_meta`` so the
                response shape matches what MCP clients expect.
            **context: Extra key-value pairs merged into the serialized dict
                (e.g. ``symbol_id="foo"``).
        """
        self.detail = detail
        self.context = context
        self._meta = _meta
        super().__init__(detail)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a tool-response error dict.

        Returns:
            Dict with ``error`` code, optional ``detail`` message, any extra
            context keys, and ``_meta`` if one was provided.
        """
        result: dict[str, Any] = {"error": self.code}
        if self.detail:
            result["detail"] = self.detail
        result.update(self.context)
        if self._meta is not None:
            result["_meta"] = self._meta
        return result


class SymbolNotFoundError(SylvanError):
    """Raised when a symbol ID does not exist in the index.

    Attributes:
        code: ``"symbol_not_found"``.
    """

    code = "symbol_not_found"


class SectionNotFoundError(SylvanError):
    """Raised when a section ID does not exist in the index.

    Attributes:
        code: ``"section_not_found"``.
    """

    code = "section_not_found"


class RepoNotFoundError(SylvanError):
    """Raised when a repository name is not indexed.

    Attributes:
        code: ``"repo_not_found"``.
    """

    code = "repo_not_found"


class IndexFileNotFoundError(SylvanError):
    """Raised when a file path does not exist in the index.

    Attributes:
        code: ``"file_not_found"``.
    """

    code = "file_not_found"


class WorkspaceNotFoundError(SylvanError):
    """Raised when a workspace name does not exist.

    Attributes:
        code: ``"workspace_not_found"``.
    """

    code = "workspace_not_found"


class SourceNotAvailableError(SylvanError):
    """Raised when symbol source code cannot be retrieved from blobs.

    Attributes:
        code: ``"source_not_available"``.
    """

    code = "source_not_available"


class ContentNotAvailableError(SylvanError):
    """Raised when section content cannot be retrieved from blobs.

    Attributes:
        code: ``"content_not_available"``.
    """

    code = "content_not_available"


class EmptyQueryError(SylvanError):
    """Raised when a search query is empty or whitespace-only.

    Attributes:
        code: ``"empty_query"``.
    """

    code = "empty_query"


class PathTooBroadError(SylvanError):
    """Raised when an indexing path is dangerously broad (e.g. ``/`` or ``C:\\\\``).

    Attributes:
        code: ``"path_too_broad"``.
    """

    code = "path_too_broad"


class IndexNotADirectoryError(SylvanError):
    """Raised when a path expected to be a directory is not.

    Attributes:
        code: ``"not_a_directory"``.
    """

    code = "not_a_directory"


class NoFilesFoundError(SylvanError):
    """Raised when file discovery finds zero indexable files.

    Attributes:
        code: ``"no_files_found"``.
    """

    code = "no_files_found"


class ParseError(SylvanError):
    """Raised when a file fails to parse.

    Attributes:
        code: ``"parse_error"``.
    """

    code = "parse_error"


class _LegacyError:
    """Thin shim that reproduces the old (non-Exception) SylvanError shape.

    The old class serialized to ``{"error_code": ..., "error": ..., "details": ...}``.
    This shim preserves that exact format so ``test_errors.py`` keeps passing.

    Attributes:
        code: Uppercase error code (e.g. ``"SYMBOL_NOT_FOUND"``).
        message: Human-readable message.
        details: Extra context dict.
    """

    __slots__ = ("code", "details", "message")

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        """Create a legacy structured error.

        Args:
            code: Machine-readable error code (e.g. ``SYMBOL_NOT_FOUND``).
            message: Human-readable error description.
            details: Optional extra context about the error.
        """
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        """Serialize the error to a plain dictionary.

        Returns:
            Dictionary with ``error_code``, ``error``, and optionally ``details``.
        """
        result: dict[str, Any] = {"error_code": self.code, "error": self.message}
        if self.details:
            result["details"] = self.details
        return result


def symbol_not_found(symbol_id: str) -> dict:
    """Build an error dict for a missing symbol.

    Args:
        symbol_id: The requested symbol identifier.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "SYMBOL_NOT_FOUND",
        f"No symbol with ID '{symbol_id}' exists in the index.",
        {"symbol_id": symbol_id},
    ).to_dict()


def section_not_found(section_id: str) -> dict:
    """Build an error dict for a missing section.

    Args:
        section_id: The requested section identifier.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "SECTION_NOT_FOUND",
        f"No section with ID '{section_id}' exists in the index.",
        {"section_id": section_id},
    ).to_dict()


def repo_not_found(repo: str) -> dict:
    """Build an error dict for a missing repository.

    Args:
        repo: The requested repository name.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "REPO_NOT_FOUND",
        f"Repository '{repo}' is not indexed. Run index_folder first.",
        {"repo": repo},
    ).to_dict()


def workspace_not_found(workspace: str) -> dict:
    """Build an error dict for a missing workspace.

    Args:
        workspace: The requested workspace name.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "WORKSPACE_NOT_FOUND",
        f"Workspace '{workspace}' does not exist. Create it with index_workspace.",
        {"workspace": workspace},
    ).to_dict()


def not_a_directory(path: str) -> dict:
    """Build an error dict for a path that is not a directory.

    Args:
        path: The requested file-system path.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "NOT_A_DIRECTORY",
        f"Path '{path}' is not a directory or does not exist.",
        {"path": path},
    ).to_dict()


def source_not_available(symbol_id: str) -> dict:
    """Build an error dict when symbol source cannot be retrieved.

    Args:
        symbol_id: The symbol whose source is missing.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "SOURCE_NOT_AVAILABLE",
        f"Source content for '{symbol_id}' could not be retrieved from the blob store.",
        {"symbol_id": symbol_id},
    ).to_dict()


def content_not_available(section_id: str) -> dict:
    """Build an error dict when section content cannot be retrieved.

    Args:
        section_id: The section whose content is missing.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "CONTENT_NOT_AVAILABLE",
        f"Content for section '{section_id}' could not be retrieved.",
        {"section_id": section_id},
    ).to_dict()


def empty_query() -> dict:
    """Build an error dict for an empty or meaningless search query.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "EMPTY_QUERY",
        "Search query is empty or contains only special characters.",
    ).to_dict()


def parse_error(path: str, detail: str) -> dict:
    """Build an error dict for a file parse failure.

    Args:
        path: Path to the file that failed to parse.
        detail: Description of the parse failure.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "PARSE_ERROR",
        f"Failed to parse '{path}'.",
        {"path": path, "detail": detail},
    ).to_dict()


def no_files_found(path: str) -> dict:
    """Build an error dict when no indexable files are found.

    Args:
        path: The directory that was searched.

    Returns:
        Serialized legacy error dictionary.
    """
    return _LegacyError(
        "NO_FILES_FOUND",
        f"No indexable files found in '{path}'. Check filters and file types.",
        {"path": path},
    ).to_dict()
