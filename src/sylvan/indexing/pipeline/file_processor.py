"""Per-file processing -- read, hash-check, parse, and store a single file."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sylvan.indexing.discovery.file_discovery import hash_content
from sylvan.indexing.source_code.import_extraction import extract_imports
from sylvan.indexing.source_code.language_specs import detect_language
from sylvan.indexing.source_code.parse_orchestration import parse_source_file
from sylvan.indexing.storage.file_store import clear_stale_data, upsert_file
from sylvan.indexing.storage.import_store import store_imports
from sylvan.indexing.storage.section_store import store_sections
from sylvan.indexing.storage.symbol_store import store_call_sites, store_symbols

if TYPE_CHECKING:
    from pathlib import Path

    from sylvan.indexing.pipeline.orchestrator import IndexResult


_DOC_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".mdx",
        ".rst",
        ".adoc",
        ".txt",
        ".html",
        ".htm",
        ".ipynb",
        ".json",
        ".jsonc",
        ".yaml",
        ".yml",
        ".xml",
        ".svg",
    }
)
"""File extensions recognized as documentation formats."""


@dataclass(slots=True)
class FileProcessingResult:
    """Extraction result from a single file - no DB, no async."""

    relative_path: str
    content_hash: str
    content_bytes: bytes
    byte_size: int
    mtime: float
    language: str | None
    symbols: list = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    sections: list = field(default_factory=list)
    call_sites: list = field(default_factory=list)
    content_str: str = ""
    parse_error: str | None = None
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    has_content_handler: bool = False
    deferred_parents: list[tuple[str, str]] = field(default_factory=list)


def _extract_file(
    df_path: Path,
    df_relative_path: str,
    df_size: int,
    df_mtime: float,
    max_file_size: int,
    repo_name: str,
    existing_hash: str | None,
    *,
    force: bool = False,
) -> FileProcessingResult:
    """Sync extraction - reads file, parses symbols/imports/sections. No DB calls."""
    try:
        content_bytes = df_path.read_bytes()
    except OSError as e:
        return FileProcessingResult(
            relative_path=df_relative_path,
            content_hash="",
            content_bytes=b"",
            byte_size=0,
            mtime=df_mtime,
            language=None,
            error=str(e),
        )

    if len(content_bytes) > max_file_size:
        return FileProcessingResult(
            relative_path=df_relative_path,
            content_hash="",
            content_bytes=content_bytes,
            byte_size=len(content_bytes),
            mtime=df_mtime,
            language=None,
            skipped=True,
            skip_reason="exceeds_max_file_size",
        )

    content_hash = hash_content(content_bytes)

    if not force and existing_hash is not None and existing_hash == content_hash:
        return FileProcessingResult(
            relative_path=df_relative_path,
            content_hash=content_hash,
            content_bytes=content_bytes,
            byte_size=df_size,
            mtime=df_mtime,
            language=None,
            skipped=True,
            skip_reason="unchanged",
        )

    try:
        content_str = content_bytes.decode("utf-8", errors="replace")
    except Exception:
        content_str = ""

    language = detect_language(df_relative_path)

    result = FileProcessingResult(
        relative_path=df_relative_path,
        content_hash=content_hash,
        content_bytes=content_bytes,
        content_str=content_str,
        byte_size=df_size,
        mtime=df_mtime,
        language=language,
    )

    if not content_str:
        return result

    from sylvan.extensions import get_content_handler

    if get_content_handler(df_relative_path, content_str):
        result.has_content_handler = True

    if language and not result.has_content_handler:
        parse_result = parse_source_file(df_relative_path, content_str, language)
        prefix = f"{repo_name}::"
        for sym in parse_result.symbols:
            sym.symbol_id = prefix + sym.symbol_id
            if sym.parent_symbol_id:
                sym.parent_symbol_id = prefix + sym.parent_symbol_id
            result.symbols.append(sym)
            if sym.parent_symbol_id:
                result.deferred_parents.append((sym.symbol_id, sym.parent_symbol_id))

        if parse_result.error:
            result.parse_error = parse_result.error

        if result.symbols:
            from sylvan.indexing.source_code.call_extractor import extract_call_sites

            result.call_sites = extract_call_sites(
                parse_result.symbols,
                content_str,
                language,
                repo_name,
            )

        for imp_dict in extract_imports(content_str, df_relative_path, language):
            result.imports.append(imp_dict)

    ext = "." + df_relative_path.rsplit(".", 1)[-1].lower() if "." in df_relative_path else ""
    if ext in _DOC_EXTENSIONS:
        try:
            from sylvan.indexing.documents.parser import parse_document

            result.sections = parse_document(content_str, df_relative_path, repo_name)
        except ImportError:
            pass
        except Exception as e:
            result.parse_error = f"doc_parse: {e}"

    return result


async def _persist_result(
    result: FileProcessingResult,
    repo_id: int,
    repo_name: str,
    existing_file_id: int | None,
    index_result: IndexResult,
) -> tuple[int, int, int]:
    """Write extraction results to DB via storage modules.

    Args:
        result: File processing result.
        repo_id: Repository database ID.
        repo_name: Repository display name.
        existing_file_id: Existing file ID if re-indexing, None if new.
        index_result: Accumulator for indexing statistics.

    Returns:
        Tuple of (symbols_count, imports_count, sections_count).
    """
    file_id = await upsert_file(result, repo_id)

    if existing_file_id is not None:
        await clear_stale_data(file_id)

    if not result.content_str:
        return 0, 0, 0

    if result.has_content_handler:
        from sylvan.extensions import get_content_handler

        handler = get_content_handler(result.relative_path, result.content_str)
        if handler:
            await handler(file_id, result.relative_path, result.content_str, index_result, repo_name)

        if result.language:
            await _store_code_symbols_legacy(
                file_id,
                result.relative_path,
                result.content_str,
                result.language,
                repo_name,
                index_result,
            )
            await _store_imports_legacy(
                file_id,
                result.content_str,
                result.relative_path,
                result.language,
                index_result,
            )
    else:
        symbols_count = await store_symbols(file_id, result, index_result)
        imports_count = await store_imports(file_id, result, index_result)
        await store_call_sites(result)

        if result.parse_error and "doc_parse" not in (result.parse_error or ""):
            index_result.errors.append(
                {"error": "parse_error", "path": result.relative_path, "detail": result.parse_error}
            )

    sections_count = await store_sections(file_id, result, index_result)

    if result.parse_error and result.parse_error.startswith("doc_parse:"):
        index_result.errors.append(
            {
                "error": "doc_parse_error",
                "path": result.relative_path,
                "detail": result.parse_error.removeprefix("doc_parse: "),
            }
        )

    return (
        symbols_count if not result.has_content_handler else 0,
        imports_count if not result.has_content_handler else 0,
        sections_count,
    )


async def _store_code_symbols_legacy(
    file_id: int,
    file_path: str,
    content: str,
    language: str,
    repo_name: str,
    result: IndexResult,
) -> None:
    """Parse source code and upsert extracted symbols.

    Used by the content handler path where extraction happens at persist time.

    Args:
        file_id: File record ID.
        file_path: Relative file path.
        content: File content string.
        language: Language identifier.
        repo_name: Repository display name.
        result: Accumulator for indexing statistics.
    """
    from sylvan.database.orm import Symbol

    parse_result = parse_source_file(file_path, content, language)
    deferred_parents: list[tuple[str, str]] = []

    prefix = f"{repo_name}::"
    for sym in parse_result.symbols:
        sym.symbol_id = prefix + sym.symbol_id
        if sym.parent_symbol_id:
            sym.parent_symbol_id = prefix + sym.parent_symbol_id
        sym.file_id = file_id
        await Symbol.upsert(
            conflict_columns=["symbol_id"],
            update_columns=[
                "file_id",
                "name",
                "qualified_name",
                "kind",
                "language",
                "signature",
                "docstring",
                "summary",
                "decorators",
                "keywords",
                "line_start",
                "line_end",
                "byte_offset",
                "byte_length",
                "content_hash",
                "cyclomatic",
                "max_nesting",
                "param_count",
            ],
            file_id=file_id,
            symbol_id=sym.symbol_id,
            name=sym.name,
            qualified_name=sym.qualified_name,
            kind=sym.kind,
            language=sym.language,
            signature=sym.signature,
            docstring=sym.docstring,
            summary=sym.summary,
            decorators=sym.decorators or [],
            keywords=sym.keywords or [],
            line_start=sym.line_start,
            line_end=sym.line_end,
            byte_offset=sym.byte_offset,
            byte_length=sym.byte_length,
            content_hash=sym.content_hash,
            cyclomatic=getattr(sym, "cyclomatic", 0) or 0,
            max_nesting=getattr(sym, "max_nesting", 0) or 0,
            param_count=getattr(sym, "param_count", 0) or 0,
        )
        if sym.parent_symbol_id:
            deferred_parents.append((sym.symbol_id, sym.parent_symbol_id))
        result.symbols_extracted += 1

    if deferred_parents:
        for child_id, parent_id in deferred_parents:
            await Symbol.where(symbol_id=child_id).update(parent_symbol_id=parent_id)

    if parse_result.error:
        result.errors.append({"error": "parse_error", "path": file_path, "detail": parse_result.error})


async def _store_imports_legacy(
    file_id: int,
    content: str,
    file_path: str,
    language: str,
    result: IndexResult,
) -> None:
    """Extract and store file-level imports.

    Used by the content handler path where extraction happens at persist time.

    Args:
        file_id: File record ID.
        content: File content string.
        file_path: Relative file path.
        language: Language identifier.
        result: Accumulator for indexing statistics.
    """
    from sylvan.database.orm import FileImport

    for imp_dict in extract_imports(content, file_path, language):
        await FileImport.create(
            file_id=file_id,
            specifier=imp_dict["specifier"],
            names=imp_dict.get("names", []),
        )
        result.imports_extracted += 1
