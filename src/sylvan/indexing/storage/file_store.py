"""File record persistence - upsert, blob storage, stale cleanup."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sylvan.indexing.pipeline.file_processor import FileProcessingResult


async def upsert_file(
    result: FileProcessingResult,
    repo_id: int,
) -> int:
    """Upsert the file record and store its content blob.

    Args:
        result: File processing result with content and metadata.
        repo_id: Repository database ID.

    Returns:
        The file record ID.
    """
    from sylvan.database.orm import FileRecord
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
    return file_obj.id


async def clear_stale_data(file_id: int) -> None:
    """Remove stale vec/quality rows and old symbols/imports/sections for a re-indexed file.

    Args:
        file_id: The file record ID to clean up.
    """
    from sylvan.database.orm import FileImport, Reference, Section, Symbol

    symbol_ids = await Symbol.where(file_id=file_id).pluck("symbol_id")
    section_ids = await Section.where(file_id=file_id).pluck("section_id")

    # Vec tables don't have ORM models yet - use backend directly.
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()
    with contextlib.suppress(Exception):
        for sid in symbol_ids:
            await backend.execute("DELETE FROM symbols_vec WHERE symbol_id = ?", [sid])
    with contextlib.suppress(Exception):
        for sid in section_ids:
            await backend.execute("DELETE FROM sections_vec WHERE section_id = ?", [sid])
    with contextlib.suppress(Exception):
        for sid in symbol_ids:
            await backend.execute("DELETE FROM quality WHERE symbol_id = ?", [sid])

    for sid in symbol_ids:
        await Reference.where(source_symbol_id=sid).delete()

    await Symbol.where(file_id=file_id).delete()
    await FileImport.where(file_id=file_id).delete()
    await Section.where(file_id=file_id).delete()
