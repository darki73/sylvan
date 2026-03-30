"""Per-file processing -- read, hash-check, parse, and store a single file."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sylvan.indexing.discovery.file_discovery import hash_content
from sylvan.indexing.source_code.import_extraction import extract_imports
from sylvan.indexing.source_code.language_specs import detect_language
from sylvan.indexing.source_code.parse_orchestration import parse_source_file

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
    """Write extraction results to DB using bulk operations.

    Returns (symbols_count, imports_count, sections_count).
    """
    from sylvan.database.orm import FileImport, FileRecord, Section, Symbol
    from sylvan.database.orm.models.blob import Blob

    await Blob.store(result.content_hash, result.content_bytes)

    file_obj = await FileRecord.upsert(
        conflict_columns=["repo_id", "path"],
        update_columns=["language", "content_hash", "byte_size", "mtime"],
        repo_id=repo_id,
        path=result.relative_path,
        language=result.language,
        content_hash=result.content_hash,
        byte_size=result.byte_size,
        mtime=result.mtime,
    )
    file_id = file_obj.id

    if existing_file_id is not None:
        await _clear_stale_data(file_id)

    if not result.content_str:
        return 0, 0, 0

    symbols_count = 0
    imports_count = 0
    sections_count = 0

    if result.has_content_handler:
        from sylvan.extensions import get_content_handler

        handler = get_content_handler(result.relative_path, result.content_str)
        if handler:
            await handler(file_id, result.relative_path, result.content_str, index_result, repo_name)

        if result.language:
            await _store_code_symbols(
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
        if result.symbols:
            sym_records = []
            for sym in result.symbols:
                sym_records.append(
                    {
                        "file_id": file_id,
                        "symbol_id": sym.symbol_id,
                        "name": sym.name,
                        "qualified_name": sym.qualified_name,
                        "kind": sym.kind,
                        "language": sym.language,
                        "signature": sym.signature,
                        "docstring": sym.docstring,
                        "summary": sym.summary,
                        "decorators": sym.decorators or [],
                        "keywords": sym.keywords or [],
                        "line_start": sym.line_start,
                        "line_end": sym.line_end,
                        "byte_offset": sym.byte_offset,
                        "byte_length": sym.byte_length,
                        "content_hash": sym.content_hash,
                    }
                )
            await Symbol.bulk_upsert(
                sym_records,
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
                ],
            )
            symbols_count = len(sym_records)
            index_result.symbols_extracted += symbols_count

            if result.deferred_parents:
                from sylvan.database.orm.runtime.connection_manager import get_backend

                backend = get_backend()
                for child_id, parent_id in result.deferred_parents:
                    await backend.execute(
                        "UPDATE symbols SET parent_symbol_id = ? WHERE symbol_id = ?",
                        [parent_id, child_id],
                    )

        if result.imports:
            imp_records = [
                {
                    "file_id": file_id,
                    "specifier": imp["specifier"],
                    "names": imp.get("names", []),
                }
                for imp in result.imports
            ]
            await FileImport.bulk_create(imp_records)
            imports_count = len(imp_records)
            index_result.imports_extracted += imports_count

    if result.parse_error and "doc_parse" not in (result.parse_error or ""):
        index_result.errors.append(
            {
                "error": "parse_error",
                "path": result.relative_path,
                "detail": result.parse_error,
            }
        )

    if result.sections:
        sec_records = []
        content_str = result.content_str
        for sec in result.sections:
            body_text = content_str[sec.byte_start : sec.byte_end][:500] if sec.byte_start is not None else ""
            sec_records.append(
                {
                    "file_id": file_id,
                    "section_id": sec.section_id,
                    "title": sec.title,
                    "level": sec.level,
                    "parent_section_id": sec.parent_section_id,
                    "byte_start": sec.byte_start,
                    "byte_end": sec.byte_end,
                    "summary": sec.summary,
                    "tags": sec.tags or [],
                    "references": sec.references or [],
                    "content_hash": sec.content_hash,
                    "body_text": body_text,
                }
            )
        await Section.bulk_create(sec_records)
        sections_count = len(sec_records)
        index_result.sections_extracted += sections_count

    if result.parse_error and result.parse_error.startswith("doc_parse:"):
        index_result.errors.append(
            {
                "error": "doc_parse_error",
                "path": result.relative_path,
                "detail": result.parse_error.removeprefix("doc_parse: "),
            }
        )

    return symbols_count, imports_count, sections_count


async def _clear_stale_data(file_id: int) -> None:
    """Remove stale vec/quality rows and old symbols/imports/sections for a re-indexed file."""
    import contextlib

    from sylvan.database.orm import FileImport, Section, Symbol
    from sylvan.database.orm.runtime.connection_manager import get_backend as _get_backend

    symbol_ids = await Symbol.where(file_id=file_id).pluck("symbol_id")
    section_ids = await Section.where(file_id=file_id).pluck("section_id")

    _backend = _get_backend()
    with contextlib.suppress(Exception):
        for sid in symbol_ids:
            await _backend.execute("DELETE FROM symbols_vec WHERE symbol_id = ?", [sid])
    with contextlib.suppress(Exception):
        for sid in section_ids:
            await _backend.execute("DELETE FROM sections_vec WHERE section_id = ?", [sid])
    with contextlib.suppress(Exception):
        for sid in symbol_ids:
            await _backend.execute("DELETE FROM quality WHERE symbol_id = ?", [sid])

    await Symbol.where(file_id=file_id).delete()
    await FileImport.where(file_id=file_id).delete()
    await Section.where(file_id=file_id).delete()


async def process_file(
    df: object,
    repo_id: int,
    repo_name: str,
    max_file_size: int,
    result: IndexResult,
    *,
    force: bool = False,
) -> None:
    """Read, hash-check, parse, and store a single discovered file.

    Backward-compatible wrapper that calls _extract_file then _persist_result.
    """
    from sylvan.database.orm import FileRecord

    existing = await FileRecord.where(repo_id=repo_id, path=df.relative_path).first()
    existing_hash = existing.content_hash if existing else None
    existing_file_id = existing.id if existing else None

    extraction = _extract_file(
        df.path,
        df.relative_path,
        df.size,
        df.mtime,
        max_file_size,
        repo_name,
        existing_hash,
        force=force,
    )

    if extraction.error:
        result.errors.append(
            {
                "error": "read_error",
                "path": extraction.relative_path,
                "detail": extraction.error,
            }
        )
        return

    if extraction.skipped:
        return

    await _persist_result(extraction, repo_id, repo_name, existing_file_id, result)
    result.files_indexed += 1


async def _upsert_symbol_without_parent(sym: object, file_id: int) -> None:
    """Insert a symbol without parent_symbol_id to avoid FK failures on unordered batches."""
    from sylvan.database.orm import Symbol

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
    )


async def _store_code_symbols(
    file_id: int,
    file_path: str,
    content: str,
    language: str,
    repo_name: str,
    result: IndexResult,
) -> None:
    """Parse source code and upsert extracted symbols. Used by content handler path."""
    from sylvan.database.orm.runtime.connection_manager import get_backend

    parse_result = parse_source_file(file_path, content, language)
    deferred_parents: list[tuple[str, str]] = []

    prefix = f"{repo_name}::"
    for sym in parse_result.symbols:
        sym.symbol_id = prefix + sym.symbol_id
        if sym.parent_symbol_id:
            sym.parent_symbol_id = prefix + sym.parent_symbol_id
        sym.file_id = file_id
        await _upsert_symbol_without_parent(sym, file_id)
        if sym.parent_symbol_id:
            deferred_parents.append((sym.symbol_id, sym.parent_symbol_id))
        result.symbols_extracted += 1

    if deferred_parents:
        backend = get_backend()
        for child_id, parent_id in deferred_parents:
            await backend.execute(
                "UPDATE symbols SET parent_symbol_id = ? WHERE symbol_id = ?",
                [parent_id, child_id],
            )

    if parse_result.error:
        result.errors.append(
            {
                "error": "parse_error",
                "path": file_path,
                "detail": parse_result.error,
            }
        )


async def _store_imports_legacy(
    file_id: int,
    content: str,
    file_path: str,
    language: str,
    result: IndexResult,
) -> None:
    """Extract and store file-level imports. Used by content handler path."""
    from sylvan.database.orm import FileImport

    for imp_dict in extract_imports(content, file_path, language):
        await FileImport.create(
            file_id=file_id,
            specifier=imp_dict["specifier"],
            names=imp_dict.get("names", []),
        )
        result.imports_extracted += 1


async def store_doc_sections(
    file_id: int,
    file_path: str,
    content: str,
    repo_name: str,
    result: IndexResult,
) -> None:
    """Parse documentation sections from a file and store them."""
    from sylvan.database.orm import Section

    ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if ext not in _DOC_EXTENSIONS:
        return

    try:
        from sylvan.indexing.documents.parser import parse_document

        for sec in parse_document(content, file_path, repo_name):
            sec.file_id = file_id
            body_text = content[sec.byte_start : sec.byte_end][:500] if sec.byte_start is not None else ""
            await Section.create(
                file_id=sec.file_id,
                section_id=sec.section_id,
                title=sec.title,
                level=sec.level,
                parent_section_id=sec.parent_section_id,
                byte_start=sec.byte_start,
                byte_end=sec.byte_end,
                summary=sec.summary,
                tags=sec.tags or [],
                references=sec.references or [],
                content_hash=sec.content_hash,
                body_text=body_text,
            )
            result.sections_extracted += 1
    except ImportError:
        pass
    except Exception as e:
        result.errors.append({"error": "doc_parse_error", "path": file_path, "detail": str(e)})
