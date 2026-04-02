"""Model presenters for consistent tool response serialization.

Each presenter converts an ORM model instance to a dict with guaranteed
field names and structure. Tools and services call these instead of
manually building dicts from model attributes.

Three detail levels:
- brief: minimal fields for lists and search results
- standard: brief + signature, language, summary
- full: standard + source, docstring, decorators
"""

from __future__ import annotations

from typing import Any


class SymbolPresenter:
    """Serialize Symbol ORM instances to response dicts."""

    @staticmethod
    def brief(sym: Any) -> dict:
        """Minimal representation for search results and lists."""
        return {
            "symbol_id": sym.symbol_id,
            "name": sym.name,
            "kind": sym.kind,
            "file": getattr(sym, "_file_path", None) or "",
            "line_start": sym.line_start,
        }

    @staticmethod
    def standard(sym: Any, file_path: str | None = None) -> dict:
        """Standard representation with signature and language."""
        return {
            "symbol_id": sym.symbol_id,
            "name": sym.name,
            "qualified_name": sym.qualified_name,
            "kind": sym.kind,
            "language": sym.language,
            "file": file_path or getattr(sym, "_file_path", None) or "",
            "signature": sym.signature or "",
            "summary": getattr(sym, "summary", "") or "",
            "line_start": sym.line_start,
        }

    @staticmethod
    def full(sym: Any, file_path: str | None = None, source: str | None = None) -> dict:
        """Full representation with source, docstring, and decorators."""
        return {
            "symbol_id": sym.symbol_id,
            "name": sym.name,
            "qualified_name": sym.qualified_name,
            "kind": sym.kind,
            "language": sym.language,
            "file": file_path or getattr(sym, "_file_path", None) or "",
            "signature": sym.signature or "",
            "summary": getattr(sym, "summary", "") or "",
            "docstring": sym.docstring or "",
            "decorators": sym.decorators or [],
            "source": source or "",
            "line_start": sym.line_start,
            "line_end": sym.line_end,
        }

    @staticmethod
    def sibling(sym: Any) -> dict:
        """Compact representation for sibling symbols in context bundles."""
        return {
            "symbol_id": sym.symbol_id,
            "name": sym.name,
            "kind": sym.kind,
            "signature": sym.signature or "",
            "line_start": sym.line_start,
        }

    @staticmethod
    def outline(sym: Any) -> dict:
        """Representation for file outlines."""
        return {
            "symbol_id": sym.symbol_id,
            "name": sym.name,
            "kind": sym.kind,
            "signature": sym.signature or "",
            "line_start": sym.line_start,
            "line_end": sym.line_end,
            "parent_symbol_id": getattr(sym, "parent_symbol_id", None),
        }


class FilePresenter:
    """Serialize FileRecord ORM instances to response dicts."""

    @staticmethod
    def brief(file: Any) -> dict:
        """Minimal representation for importer lists."""
        return {
            "path": file.path,
            "language": file.language,
        }

    @staticmethod
    def with_counts(file: Any, symbol_count: int = 0) -> dict:
        """File with symbol count for outlines and importers."""
        return {
            "path": file.path,
            "language": file.language,
            "symbol_count": symbol_count,
        }


class ImportPresenter:
    """Serialize FileImport ORM instances to response dicts."""

    @staticmethod
    def standard(imp: Any) -> dict:
        """Standard import representation for context bundles."""
        return {
            "specifier": imp.specifier,
            "names": imp.names or [],
        }


class SectionPresenter:
    """Serialize Section ORM instances to response dicts."""

    @staticmethod
    def brief(section: Any) -> dict:
        """Minimal representation for search results and TOC."""
        return {
            "section_id": section.section_id,
            "title": section.title,
            "level": section.level,
            "doc_path": getattr(section, "_doc_path", None) or "",
        }

    @staticmethod
    def standard(section: Any, doc_path: str | None = None) -> dict:
        """Standard representation with summary."""
        return {
            "section_id": section.section_id,
            "title": section.title,
            "level": section.level,
            "doc_path": doc_path or getattr(section, "_doc_path", None) or "",
            "summary": section.summary or "",
            "tags": section.tags or [],
        }

    @staticmethod
    def full(section: Any, content: str | None = None, doc_path: str | None = None) -> dict:
        """Full representation with content."""
        return {
            "section_id": section.section_id,
            "title": section.title,
            "level": section.level,
            "doc_path": doc_path or getattr(section, "_doc_path", None) or "",
            "summary": section.summary or "",
            "tags": section.tags or [],
            "content": content or "",
        }


class ReferencePresenter:
    """Serialize reference/caller/callee data to response dicts."""

    @staticmethod
    def caller(ref: dict) -> dict:
        """Caller representation from reference graph queries."""
        return {
            "symbol_id": ref.get("source_symbol_id", ""),
            "name": ref.get("name", ""),
            "kind": ref.get("kind", ""),
            "file": ref.get("file_path", ""),
            "signature": ref.get("signature", ""),
            "line": ref.get("line"),
        }

    @staticmethod
    def callee(ref: dict) -> dict:
        """Callee representation from reference graph queries."""
        return {
            "symbol_id": ref.get("target_symbol_id", ""),
            "name": ref.get("name", ""),
            "kind": ref.get("kind", ""),
            "file": ref.get("file_path", ""),
            "signature": ref.get("signature", ""),
            "line": ref.get("line"),
        }
