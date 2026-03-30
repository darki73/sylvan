"""Top-level indexing coordinator -- discover files, then delegate processing.

Two-phase pipeline:
  Phase 1 (threads): read files, hash, parse tree-sitter, extract imports/sections.
  Phase 2 (event loop): batch-write results to DB in short transactions.
"""

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sylvan.config import get_config
from sylvan.database.orm import Repo
from sylvan.error_codes import IndexNotADirectoryError, PathTooBroadError
from sylvan.indexing.discovery.file_discovery import DiscoveryResult, discover_files
from sylvan.indexing.pipeline.file_processor import _extract_file, _persist_result
from sylvan.logging import get_logger

logger = get_logger(__name__)

_BATCH_SIZE = 100
"""Files per DB transaction. Short transactions free the write lock between batches."""

_MAX_WORKERS = min(4, os.cpu_count() or 2)
"""Thread pool size for CPU-bound file parsing."""


@dataclass(slots=True)
class IndexResult:
    """Accumulates counts, errors, and warnings during indexing.

    Attributes:
        repo_id: Database ID of the indexed repository.
        repo_name: Display name of the repository.
        files_indexed: Number of files successfully processed.
        files_skipped: Number of files skipped during discovery.
        symbols_extracted: Total number of code symbols extracted.
        sections_extracted: Total number of documentation sections extracted.
        imports_extracted: Total number of import statements extracted.
        imports_resolved: Number of imports resolved to target files.
        errors: Structured error records encountered during indexing.
        warnings: Structured warning records encountered during indexing.
        skipped_reasons: Mapping of skip reasons to their occurrence counts.
        duration_ms: Wall-clock duration of the indexing run in milliseconds.
        git_head: Git HEAD commit hash at the time of indexing, if available.
    """

    repo_id: int = 0
    repo_name: str = ""
    files_indexed: int = 0
    files_skipped: int = 0
    symbols_extracted: int = 0
    sections_extracted: int = 0
    imports_extracted: int = 0
    imports_resolved: int = 0
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    duration_ms: float = 0
    git_head: str | None = None

    def to_dict(self) -> dict:
        """Serialize the result to a plain dictionary.

        Returns:
            Dictionary representation of all indexing metrics.
        """
        result = {
            "repo_id": self.repo_id,
            "repo_name": self.repo_name,
            "files_indexed": self.files_indexed,
            "files_skipped": self.files_skipped,
            "symbols_extracted": self.symbols_extracted,
            "sections_extracted": self.sections_extracted,
            "imports_extracted": self.imports_extracted,
            "imports_resolved": self.imports_resolved,
            "errors": self.errors,
            "skipped_reasons": self.skipped_reasons,
            "duration_ms": round(self.duration_ms, 1),
            "git_head": self.git_head,
        }
        if self.warnings:
            result["warnings"] = self.warnings
        return result


async def index_folder(
    folder_path: str,
    name: str | None = None,
    *,
    force: bool = False,
) -> IndexResult:
    """Index a local folder: discover files, parse, extract symbols, store.

    Two-phase pipeline:
      1. Discovery + extraction run in threads (non-blocking).
      2. DB writes run on the event loop in batched transactions.

    Requires a SylvanContext with a backend to be set before calling.

    Args:
        folder_path: Absolute or relative path to the folder to index.
        name: Optional display name for the repository.
        force: If True, re-extract all files even if unchanged.

    Returns:
        An IndexResult with counts, errors, and timing information.
    """
    from sylvan.database.orm import FileRecord
    from sylvan.database.orm.runtime.connection_manager import get_backend

    start = time.monotonic()
    result = IndexResult()
    cfg = get_config()

    root = _validate_path(folder_path, result)

    if name is None:
        name = root.name
    result.repo_name = name

    # Phase 0: discovery in thread (subprocess + os.walk + stat)
    discovery = await asyncio.to_thread(
        discover_files,
        root,
        cfg.max_files_local,
        cfg.max_file_size,
    )
    result.files_skipped = discovery.total_skipped
    result.skipped_reasons = {k: len(v) for k, v in discovery.skipped.items()}
    result.git_head = discovery.git_head

    if not discovery.files:
        result.errors.append({"error": "no_files_found", "path": root.name})
        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    # Upsert repo record (needed for repo_id before anything else)
    backend = get_backend()
    async with backend.transaction():
        repo_id = await _upsert_repo(name, root, discovery)
        result.repo_id = repo_id

    # Pre-load existing file hashes in one query (avoid per-file DB lookups in threads)
    existing_files = {f.path: f for f in await FileRecord.where(repo_id=repo_id).get()}
    existing_hashes = {path: f.content_hash for path, f in existing_files.items()}

    # Phase 1: extraction in thread pool (CPU-bound parsing, file I/O)
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:

        def _make_task(df):
            return _extract_file(
                df.path,
                df.relative_path,
                df.size,
                df.mtime,
                cfg.max_file_size,
                name,
                existing_hashes.get(df.relative_path),
                force=force,
            )

        futures = [loop.run_in_executor(pool, _make_task, df) for df in discovery.files]
        extraction_results = await asyncio.gather(*futures, return_exceptions=True)

    # Phase 2: persist in batched transactions on event loop
    discovered_paths: set[str] = set()
    for batch_start in range(0, len(extraction_results), _BATCH_SIZE):
        batch = extraction_results[batch_start : batch_start + _BATCH_SIZE]
        async with backend.transaction():
            for file_result in batch:
                if isinstance(file_result, BaseException):
                    result.errors.append({"error": "extraction_error", "detail": str(file_result)})
                    continue
                if file_result.error:
                    result.errors.append(
                        {"error": "read_error", "path": file_result.relative_path, "detail": file_result.error}
                    )
                    continue
                if file_result.skipped:
                    discovered_paths.add(file_result.relative_path)
                    continue

                discovered_paths.add(file_result.relative_path)
                existing_file = existing_files.get(file_result.relative_path)
                existing_file_id = existing_file.id if existing_file else None

                syms, imps, secs = await _persist_result(
                    file_result,
                    repo_id,
                    name,
                    existing_file_id,
                    result,
                )
                result.files_indexed += 1
                result.symbols_extracted += syms
                result.imports_extracted += imps
                result.sections_extracted += secs

                if file_result.parse_error:
                    result.errors.append(
                        {
                            "error": "parse_error",
                            "path": file_result.relative_path,
                            "detail": file_result.parse_error,
                        }
                    )

    # Phase 3: cleanup + post-processing
    async with backend.transaction():
        await _purge_deleted_files(repo_id, discovered_paths)

    from sylvan.indexing.pipeline.import_resolver import resolve_imports

    result.imports_resolved = await resolve_imports(repo_id)

    await _enrich_ecosystem_context(root, repo_id)

    result.duration_ms = (time.monotonic() - start) * 1000
    return result


def _validate_path(folder_path: str, result: IndexResult) -> Path:
    """Resolve and validate the folder path.

    Args:
        folder_path: Path string to validate.
        result: IndexResult to record warnings into.

    Returns:
        Resolved Path on success.

    Raises:
        PathTooBroadError: If the path is dangerously broad.
        IndexNotADirectoryError: If the path is not a directory.
    """
    root = Path(folder_path).resolve()

    if len(root.parts) < 3:
        raise PathTooBroadError(
            "Path is too broad -- use an absolute path to a specific project folder.",
            path=root.name,
        )

    if not root.is_dir():
        raise IndexNotADirectoryError(
            f"Path '{root.name}' is not a directory or does not exist.",
            path=folder_path,
        )

    if not Path(folder_path).is_absolute():
        logger.warning("relative_path_resolved", original=folder_path, resolved=str(root))
        result.warnings.append(
            {
                "warning": "relative_path_resolved",
                "original": folder_path,
                "resolved": str(root),
                "detail": "A relative path was given -- resolved to an absolute path.",
            }
        )

    return root


async def _upsert_repo(name: str, root: Path, discovery: DiscoveryResult) -> int:
    """Create or update the repo record, return its ID.

    Args:
        name: Repository display name.
        root: Resolved repository root path.
        discovery: Discovery result containing git_head.

    Returns:
        Database ID of the upserted repository.
    """
    now = datetime.now(UTC).isoformat()
    repo_obj = await Repo.upsert(
        conflict_columns=["source_path"],
        update_columns=["name", "indexed_at", "git_head"],
        name=name,
        source_path=str(root),
        indexed_at=now,
        git_head=discovery.git_head,
    )
    return repo_obj.id


async def _purge_deleted_files(repo_id: int, discovered_paths: set[str]) -> None:
    """Remove database records for files that no longer exist on disk.

    Compares the set of discovered file paths against what's stored in the
    database. Any file record not in the discovered set is deleted, along
    with its symbols, sections, and imports (via CASCADE or explicit delete).

    Args:
        repo_id: Database ID of the repository.
        discovered_paths: Set of relative paths found during discovery.
    """
    from sylvan.database.orm import FileImport, FileRecord, Section, Symbol

    stored_files = await FileRecord.where(repo_id=repo_id).get()
    for file_record in stored_files:
        if file_record.path not in discovered_paths:
            await Symbol.where(file_id=file_record.id).delete()
            await FileImport.where(file_id=file_record.id).delete()
            await Section.where(file_id=file_record.id).delete()
            await file_record.delete()
            logger.debug("purged_deleted_file", path=file_record.path, repo_id=repo_id)


async def _enrich_ecosystem_context(root: Path, repo_id: int) -> None:
    """Discover ecosystem context providers and enrich indexed symbols.

    Checks for ecosystem-specific metadata (e.g., dbt project files) and
    appends extra keywords to symbols based on file-level context.

    Args:
        root: Repository root directory.
        repo_id: Database ID of the indexed repository.
    """
    from sylvan.providers.ecosystem_context.base import discover_providers, enrich_symbols

    providers = discover_providers(root)
    if not providers:
        return

    provider_names = [p.name for p in providers]
    logger.info("ecosystem_context_detected", providers=provider_names, repo_id=repo_id)

    from sylvan.database.orm import FileRecord, Symbol

    files = await FileRecord.where(repo_id=repo_id).get()
    file_ids = [f.id for f in files]
    if not file_ids:
        return

    # Build a file_id -> path lookup for setting file_path on symbols.
    file_path_map = {f.id: f.path for f in files}

    symbols = await Symbol.where(file_id__in=file_ids).get()
    if not symbols:
        return

    # Set file_path attribute so enrich_symbols can read it.
    for sym in symbols:
        sym.file_path = file_path_map.get(sym.file_id, "")

    enrich_symbols(symbols, providers)

    records = [{"id": sym.id, "keywords": sym.keywords} for sym in symbols]
    if records:
        await Symbol.bulk_upsert(
            records,
            conflict_columns=["id"],
            update_columns=["keywords"],
        )

    logger.info(
        "ecosystem_context_enriched",
        symbols=len(symbols),
        providers=provider_names,
    )
