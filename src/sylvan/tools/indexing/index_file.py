"""MCP tool: index_file -- surgical single-file reindex."""

from pathlib import Path

from sylvan.context import get_context
from sylvan.database.orm import FileImport, FileRecord, Repo, Section, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.database.orm.runtime.connection_manager import get_backend
from sylvan.error_codes import IndexFileNotFoundError, RepoNotFoundError
from sylvan.indexing.discovery.file_discovery import hash_content
from sylvan.indexing.pipeline.file_processor import store_doc_sections
from sylvan.indexing.pipeline.orchestrator import IndexResult
from sylvan.indexing.source_code.import_extraction import extract_imports
from sylvan.indexing.source_code.language_specs import detect_language
from sylvan.indexing.source_code.parse_orchestration import parse_source_file
from sylvan.tools.support.response import MetaBuilder, _staleness_cache, ensure_orm, log_tool_call, wrap_response


async def _resolve_repo(repo: str, meta: MetaBuilder) -> Repo:
    """Look up a repo by name, raising if not found.

    Args:
        repo: The repository name to look up.
        meta: The meta builder for error responses.

    Returns:
        The resolved Repo object.

    Raises:
        RepoNotFoundError: If no repository with the given name is indexed.
    """
    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())
    return repo_obj


def _validate_file_path(source_path: Path, file_path: str, meta: MetaBuilder) -> Path:
    """Resolve and validate the absolute file path within the repo root.

    Args:
        source_path: The repository root directory.
        file_path: Relative path within the repo.
        meta: The meta builder for error responses.

    Returns:
        The validated absolute file path.

    Raises:
        IndexFileNotFoundError: If the path escapes the repo root or doesn't exist.
    """
    abs_path = (source_path / file_path).resolve()

    try:
        abs_path.relative_to(source_path.resolve())
    except ValueError as exc:
        raise IndexFileNotFoundError(
            f"Path '{file_path}' resolves outside the repository root.",
            file_path=file_path, _meta=meta.build(),
        ) from exc

    if not abs_path.is_file():
        raise IndexFileNotFoundError(file_path=file_path, _meta=meta.build())

    return abs_path


async def _check_unchanged(repo_id: int, rel_path: str, content_hash: str, meta: MetaBuilder) -> dict | None:
    """Return an 'unchanged' response if the file content hash has not changed.

    Args:
        repo_id: Database ID of the repository.
        rel_path: Normalised relative path of the file.
        content_hash: SHA-256 hash of the current file content.
        meta: The meta builder for the response envelope.

    Returns:
        An 'unchanged' tool response dict, or None if the file has changed.
    """
    existing = await FileRecord.where(repo_id=repo_id, path=rel_path).first()
    if not existing or existing.content_hash != content_hash:
        return None

    has_data = True
    if existing.language:
        has_data = await Symbol.where(file_id=existing.id).count() > 0
    if has_data:
        meta.set("status", "unchanged")
        return wrap_response(
            {"file_path": rel_path, "symbols_extracted": 0, "status": "unchanged"},
            meta.build(),
        )
    return None


async def _upsert_file_record(repo_id: int, rel_path: str, language: str | None, content_hash: str, abs_path: Path) -> FileRecord:
    """Create or update the file record with current metadata.

    Args:
        repo_id: Database ID of the repository.
        rel_path: Normalised relative path of the file.
        language: Detected programming language, or None.
        content_hash: SHA-256 hash of the file content.
        abs_path: Absolute filesystem path (for stat metadata).

    Returns:
        The upserted ``FileRecord`` instance.
    """
    stat = abs_path.stat()
    return await FileRecord.upsert(
        conflict_columns=["repo_id", "path"],
        update_columns=["language", "content_hash", "byte_size", "mtime"],
        repo_id=repo_id,
        path=rel_path,
        language=language,
        content_hash=content_hash,
        byte_size=stat.st_size,
        mtime=stat.st_mtime,
    )


async def _clear_stale_data(file_id: int) -> None:
    """Delete symbols, imports, sections, and vec entries from a previous index.

    Vec entries are cleaned up first (before the parent rows disappear) since
    the virtual tables have no CASCADE support.

    Args:
        file_id: Database ID of the file record to clear.
    """
    import contextlib

    symbol_ids = await Symbol.where(file_id=file_id).pluck("symbol_id")
    section_ids = await Section.where(file_id=file_id).pluck("section_id")

    backend = get_backend()
    with contextlib.suppress(Exception):
        for sid in symbol_ids:
            await backend.execute("DELETE FROM symbols_vec WHERE symbol_id = ?", [sid])
    with contextlib.suppress(Exception):
        for sid in section_ids:
            await backend.execute("DELETE FROM sections_vec WHERE section_id = ?", [sid])

    await Symbol.where(file_id=file_id).delete()
    await FileImport.where(file_id=file_id).delete()
    await Section.where(file_id=file_id).delete()


async def _extract_symbols_and_imports(
    file_id: int,
    rel_path: str,
    content_str: str,
    language: str,
) -> tuple[int, int]:
    """Parse source code to extract symbols and imports, returning their counts.

    Args:
        file_id: Database ID of the file record.
        rel_path: Normalised relative file path.
        content_str: The file content as a UTF-8 string.
        language: The programming language identifier.

    Returns:
        Two-tuple of (symbols_extracted, imports_extracted).
    """
    parse_result = parse_source_file(rel_path, content_str, language)

    deferred_parents: list[tuple[str, str]] = []
    symbols_extracted = 0

    for sym in parse_result.symbols:
        sym.file_id = file_id
        await Symbol.upsert(
            conflict_columns=["symbol_id"],
            update_columns=[
                "file_id", "name", "qualified_name", "kind",
                "language", "signature", "docstring", "summary",
                "decorators", "keywords",
                "line_start", "line_end", "byte_offset",
                "byte_length", "content_hash",
            ],
            file_id=sym.file_id,
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
        if sym.parent_symbol_id:
            deferred_parents.append((sym.symbol_id, sym.parent_symbol_id))
        symbols_extracted += 1

    if deferred_parents:
        backend = get_backend()
        for child_id, parent_id in deferred_parents:
            await backend.execute(
                "UPDATE symbols SET parent_symbol_id = ? WHERE symbol_id = ?",
                [parent_id, child_id],
            )

    imports = extract_imports(content_str, rel_path, language)
    imports_extracted = 0
    for imp_dict in imports:
        await FileImport.create(
            file_id=file_id,
            specifier=imp_dict["specifier"],
            names=imp_dict.get("names", []),
        )
        imports_extracted += 1

    return symbols_extracted, imports_extracted


@log_tool_call
async def index_file(
    repo: str,
    file_path: str,
) -> dict:
    """Reindex a single file without touching the rest of the repo.

    Much cheaper than index_folder when only one file has changed.

    Args:
        repo: Repository name (as shown in list_repos).
        file_path: Relative path within the repo (e.g., "src/main.py").

    Returns:
        Tool response dict with indexing stats and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await _resolve_repo(repo, meta)
    repo_id = repo_obj.id
    source_path = Path(repo_obj.source_path)

    abs_path = _validate_file_path(source_path, file_path, meta)

    try:
        content_bytes = abs_path.read_bytes()
    except OSError as e:
        return wrap_response(
            {"error": f"Cannot read file: {e}"},
            meta.build(),
        )

    content_hash = hash_content(content_bytes)
    rel_path = file_path.replace("\\", "/")

    unchanged = await _check_unchanged(repo_id, rel_path, content_hash, meta)
    if unchanged:
        return unchanged

    had_existing = await FileRecord.where(repo_id=repo_id, path=rel_path).first() is not None

    backend = get_backend()

    async with backend.transaction():
        await Blob.store(content_hash, content_bytes)

        language = detect_language(rel_path)
        file_obj = await _upsert_file_record(repo_id, rel_path, language, content_hash, abs_path)
        file_id = file_obj.id

        if had_existing:
            await _clear_stale_data(file_id)

        try:
            content_str = content_bytes.decode("utf-8", errors="replace")
        except Exception:
            content_str = ""

        symbols_extracted = 0
        imports_extracted = 0
        sections_extracted = 0

        if content_str:
            if language:
                symbols_extracted, imports_extracted = await _extract_symbols_and_imports(
                    file_id, rel_path, content_str, language,
                )

            idx_result = IndexResult()
            await store_doc_sections(file_id, rel_path, content_str, repo, idx_result)
            sections_extracted = idx_result.sections_extracted

    # Resolve import specifiers to file IDs after the transaction commits.
    from sylvan.indexing.pipeline.import_resolver import resolve_imports

    await resolve_imports(repo_id)

    _staleness_cache.pop(repo_id, None)
    get_context().cache.clear()

    # Schedule background tasks (embeddings, summaries) outside the transaction.
    from sylvan.indexing.pipeline.orchestrator import _maybe_start_background

    await _maybe_start_background(repo_id)

    meta.set("status", "updated")
    meta.set("symbols_extracted", symbols_extracted)

    return wrap_response(
        {
            "file_path": rel_path,
            "symbols_extracted": symbols_extracted,
            "imports_extracted": imports_extracted,
            "sections_extracted": sections_extracted,
            "status": "updated",
        },
        meta.build(),
    )
