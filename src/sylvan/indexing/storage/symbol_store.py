"""Symbol persistence - bulk upsert, parent linking, call site references."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sylvan.indexing.pipeline.file_processor import FileProcessingResult
    from sylvan.indexing.pipeline.orchestrator import IndexResult


async def store_symbols(
    file_id: int,
    result: FileProcessingResult,
    index_result: IndexResult,
) -> int:
    """Bulk upsert extracted symbols and link parent relationships.

    Args:
        file_id: The file record ID.
        result: File processing result with symbols and deferred parents.
        index_result: Accumulator for indexing statistics.

    Returns:
        Number of symbols stored.
    """
    if not result.symbols:
        return 0

    from sylvan.database.orm import Symbol

    sym_records = [
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
            "cyclomatic": getattr(sym, "cyclomatic", 0) or 0,
            "max_nesting": getattr(sym, "max_nesting", 0) or 0,
            "param_count": getattr(sym, "param_count", 0) or 0,
        }
        for sym in result.symbols
    ]

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
            "cyclomatic",
            "max_nesting",
            "param_count",
        ],
    )

    count = len(sym_records)
    index_result.symbols_extracted += count

    if result.deferred_parents:
        await _link_parents(result.deferred_parents)

    return count


async def store_call_sites(result: FileProcessingResult) -> None:
    """Store extracted call sites as reference records.

    Args:
        result: File processing result with call sites.
    """
    if not result.call_sites:
        return

    from sylvan.database.orm import Reference

    ref_records = [
        {
            "source_symbol_id": cs.caller_symbol_id,
            "target_symbol_id": None,
            "target_specifier": cs.callee_name,
            "target_names": [],
            "line": cs.line,
        }
        for cs in result.call_sites
    ]
    await Reference.bulk_create(ref_records)


async def _link_parents(deferred_parents: list[tuple[str, str]]) -> None:
    """Link child symbols to their parent symbols.

    Args:
        deferred_parents: List of (child_symbol_id, parent_symbol_id) tuples.
    """
    from sylvan.database.orm import Symbol

    for child_id, parent_id in deferred_parents:
        await Symbol.where(symbol_id=child_id).update(parent_symbol_id=parent_id)
