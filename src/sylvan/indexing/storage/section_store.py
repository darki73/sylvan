"""Section persistence - bulk create from extraction results."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sylvan.indexing.pipeline.file_processor import FileProcessingResult
    from sylvan.indexing.pipeline.orchestrator import IndexResult


async def store_sections(
    file_id: int,
    result: FileProcessingResult,
    index_result: IndexResult,
) -> int:
    """Bulk create section records from extraction results.

    Args:
        file_id: The file record ID.
        result: File processing result with sections and content.
        index_result: Accumulator for indexing statistics.

    Returns:
        Number of sections stored.
    """
    if not result.sections:
        return 0

    from sylvan.database.orm import Section

    content_str = result.content_str
    sec_records = [
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
            "body_text": content_str[sec.byte_start : sec.byte_end][:500] if sec.byte_start is not None else "",
        }
        for sec in result.sections
    ]
    await Section.bulk_create(sec_records)

    count = len(sec_records)
    index_result.sections_extracted += count
    return count
