"""Per-file processing -- read, hash-check, parse, and store a single file."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sylvan.database.orm import FileImport, FileRecord, Section, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.indexing.discovery.file_discovery import hash_content
from sylvan.indexing.source_code.import_extraction import extract_imports
from sylvan.indexing.source_code.language_specs import detect_language
from sylvan.indexing.source_code.parse_orchestration import parse_source_file

if TYPE_CHECKING:
    from sylvan.indexing.pipeline.orchestrator import IndexResult


_DOC_EXTENSIONS = frozenset({
    ".md", ".markdown", ".mdx", ".rst", ".adoc",
    ".txt", ".html", ".htm",
    ".ipynb", ".json", ".jsonc",
    ".yaml", ".yml", ".xml", ".svg",
})
"""File extensions recognized as documentation formats."""


async def process_file(
    df: object,
    repo_id: int,
    repo_name: str,
    max_file_size: int,
    result: IndexResult,
) -> None:
    """Read, hash-check, parse, and store a single discovered file.

    Args:
        df: DiscoveredFile object with path, relative_path, size, mtime.
        repo_id: Database ID of the repository.
        repo_name: Display name of the repository.
        max_file_size: Maximum file size in bytes.
        result: IndexResult accumulator for counts and errors.
    """
    try:
        content_bytes = df.path.read_bytes()
    except OSError as e:
        result.errors.append({"error": "read_error", "path": df.relative_path, "detail": str(e)})
        return

    if len(content_bytes) > max_file_size:
        return

    content_hash = hash_content(content_bytes)
    existing = await FileRecord.where(repo_id=repo_id, path=df.relative_path).first()

    if await _file_unchanged(existing, content_hash):
        return

    await Blob.store(content_hash, content_bytes)
    language = detect_language(df.relative_path)

    file_obj = await FileRecord.upsert(
        conflict_columns=["repo_id", "path"],
        update_columns=["language", "content_hash", "byte_size", "mtime"],
        repo_id=repo_id, path=df.relative_path, language=language,
        content_hash=content_hash, byte_size=df.size, mtime=df.mtime,
    )
    file_id = file_obj.id

    if existing:
        await Symbol.where(file_id=file_id).delete()
        await FileImport.where(file_id=file_id).delete()
        await Section.where(file_id=file_id).delete()

    try:
        content_str = content_bytes.decode("utf-8", errors="replace")
    except Exception:
        content_str = ""

    if not content_str:
        result.files_indexed += 1
        return

    if language:
        await _store_code_symbols(file_id, df.relative_path, content_str, language, result)
        await _store_imports(file_id, content_str, df.relative_path, language, result)

    await store_doc_sections(file_id, df.relative_path, content_str, repo_name, result)
    result.files_indexed += 1


async def _file_unchanged(existing: FileRecord | None, content_hash: str) -> bool:
    """Return True if file content matches the stored hash and has extracted data.

    Args:
        existing: Previously stored FileRecord, or None.
        content_hash: SHA-256 hash of the current file content.

    Returns:
        True if the file is unchanged and has existing symbol data.
    """
    if existing is None or existing.content_hash != content_hash:
        return False
    if not existing.language:
        return True
    return await Symbol.where(file_id=existing.id).count() > 0


async def _upsert_symbol_without_parent(sym: object, file_id: int) -> None:
    """Insert a symbol without parent_symbol_id to avoid FK failures on unordered batches.

    Args:
        sym: Symbol validation object with all extraction fields.
        file_id: Database ID of the file containing this symbol.
    """
    await Symbol.upsert(
        conflict_columns=["symbol_id"],
        update_columns=[
            "file_id", "name", "qualified_name", "kind",
            "language", "signature", "docstring", "summary",
            "decorators", "keywords",
            "line_start", "line_end", "byte_offset",
            "byte_length", "content_hash",
        ],
        file_id=file_id, symbol_id=sym.symbol_id,
        name=sym.name, qualified_name=sym.qualified_name,
        kind=sym.kind, language=sym.language,
        signature=sym.signature, docstring=sym.docstring,
        summary=sym.summary, decorators=sym.decorators or [],
        keywords=sym.keywords or [],
        line_start=sym.line_start, line_end=sym.line_end,
        byte_offset=sym.byte_offset, byte_length=sym.byte_length,
        content_hash=sym.content_hash,
    )


async def _store_code_symbols(
    file_id: int,
    file_path: str,
    content: str,
    language: str,
    result: IndexResult,
) -> None:
    """Parse source code and upsert extracted symbols.

    Args:
        file_id: Database ID of the file.
        file_path: Relative file path.
        content: File content as a string.
        language: Detected language identifier.
        result: IndexResult accumulator for counts and errors.
    """
    from sylvan.database.orm.runtime.connection_manager import get_backend

    parse_result = parse_source_file(file_path, content, language)
    deferred_parents: list[tuple[str, str]] = []

    for sym in parse_result.symbols:
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
        result.errors.append({
            "error": "parse_error", "path": file_path, "detail": parse_result.error,
        })


async def _store_imports(
    file_id: int, content: str, file_path: str, language: str, result: IndexResult,
) -> None:
    """Extract and store file-level imports.

    Args:
        file_id: Database ID of the file.
        content: File content as a string.
        file_path: Relative file path.
        language: Detected language identifier.
        result: IndexResult accumulator for counts.
    """
    for imp_dict in extract_imports(content, file_path, language):
        await FileImport.create(
            file_id=file_id, specifier=imp_dict["specifier"], names=imp_dict.get("names", []),
        )
        result.imports_extracted += 1


async def store_doc_sections(
    file_id: int,
    file_path: str,
    content: str,
    repo_name: str,
    result: IndexResult,
) -> None:
    """Parse documentation sections from a file and store them.

    Args:
        file_id: Database ID of the file.
        file_path: Relative file path.
        content: File content as a string.
        repo_name: Repository display name.
        result: IndexResult accumulator for counts and errors.
    """
    ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if ext not in _DOC_EXTENSIONS:
        return

    try:
        from sylvan.indexing.documents.parser import parse_document
        for sec in parse_document(content, file_path, repo_name):
            sec.file_id = file_id
            body_text = content[sec.byte_start:sec.byte_end][:500] if sec.byte_start is not None else ""
            await Section.create(
                file_id=sec.file_id, section_id=sec.section_id,
                title=sec.title, level=sec.level,
                parent_section_id=sec.parent_section_id,
                byte_start=sec.byte_start, byte_end=sec.byte_end,
                summary=sec.summary, tags=sec.tags or [],
                references=sec.references or [],
                content_hash=sec.content_hash,
                body_text=body_text,
            )
            result.sections_extracted += 1
    except ImportError:
        pass
    except Exception as e:
        result.errors.append({"error": "doc_parse_error", "path": file_path, "detail": str(e)})
