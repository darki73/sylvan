"""Import persistence - bulk create from extraction results."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sylvan.indexing.pipeline.file_processor import FileProcessingResult
    from sylvan.indexing.pipeline.orchestrator import IndexResult


async def store_imports(
    file_id: int,
    result: FileProcessingResult,
    index_result: IndexResult,
) -> int:
    """Bulk create import records from extraction results.

    Args:
        file_id: The file record ID.
        result: File processing result with imports.
        index_result: Accumulator for indexing statistics.

    Returns:
        Number of imports stored.
    """
    if not result.imports:
        return 0

    from sylvan.database.orm import FileImport

    imp_records = [
        {
            "file_id": file_id,
            "specifier": imp["specifier"],
            "names": imp.get("names", []),
        }
        for imp in result.imports
    ]
    await FileImport.bulk_create(imp_records)

    count = len(imp_records)
    index_result.imports_extracted += count
    return count
