"""MCP tool: rename_symbol -- find all edit locations for renaming a symbol."""

import re

from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def rename_symbol(symbol_id: str, new_name: str) -> dict:
    """Find all files and lines where a symbol name appears for renaming.

    Looks up the symbol, uses blast radius analysis to find affected files,
    then scans each file for occurrences of the old name. Returns exact
    edit locations (file, line, old_text, new_text) for the agent to apply.

    Args:
        symbol_id: The symbol identifier to rename.
        new_name: The desired new name for the symbol.

    Returns:
        Tool response dict with ``edits`` list, ``symbol`` info,
        and ``_meta`` envelope with counts.
    """
    meta = MetaBuilder()
    ensure_orm()

    from sylvan.analysis.impact.blast_radius import get_blast_radius as _blast
    from sylvan.database.orm.models.blob import Blob
    from sylvan.database.orm.models.symbol import Symbol

    target = await (
        Symbol.query()
        .select("symbols.*", "f.path as file_path", "f.content_hash", "f.repo_id")
        .join("files f", "f.id = symbols.file_id")
        .where("symbols.symbol_id", symbol_id)
        .first()
    )

    if target is None:
        return wrap_response(
            {"error": "symbol_not_found", "symbol_id": symbol_id},
            meta.build(),
        )

    old_name = target.name
    target_file_path = getattr(target, "file_path", "")
    target_content_hash = getattr(target, "content_hash", "")

    if not new_name or not new_name.isidentifier():
        return wrap_response(
            {"error": "invalid_name", "new_name": new_name, "detail": "Must be a valid identifier"},
            meta.build(),
        )

    if old_name == new_name:
        return wrap_response(
            {"error": "same_name", "detail": "New name is identical to old name"},
            meta.build(),
        )

    pattern = re.compile(r"\b" + re.escape(old_name) + r"\b")

    edits: list[dict] = []
    files_with_edits: set[str] = set()
    hint_reads: list[dict] = []

    async def _scan_file(file_path: str, content_hash: str) -> None:
        """Scan a single file for occurrences and record edit locations."""
        content_bytes = await Blob.get(content_hash)
        if content_bytes is None:
            return

        text = content_bytes.decode("utf-8", errors="replace")
        lines = text.split("\n")

        file_has_edits = False
        for line_num, line in enumerate(lines, start=1):
            if pattern.search(line):
                edits.append(
                    {
                        "file": file_path,
                        "line": line_num,
                        "old_text": line.rstrip("\r"),
                        "new_text": pattern.sub(new_name, line).rstrip("\r"),
                    }
                )
                file_has_edits = True

        if file_has_edits:
            files_with_edits.add(file_path)
            hint_reads.append(
                {
                    "read_file": file_path,
                    "read_offset": 1,
                    "read_limit": len(lines),
                }
            )

    if target_content_hash:
        await _scan_file(target_file_path, target_content_hash)

    blast = await _blast(symbol_id, max_depth=2)
    for entry in blast.get("confirmed", []):
        file_path = entry.get("file", "")
        if file_path and file_path != target_file_path:
            from sylvan.database.orm.models.file_record import FileRecord

            file_rec = await FileRecord.where(path=file_path).first()
            if file_rec and file_rec.content_hash:
                await _scan_file(file_path, file_rec.content_hash)

    meta.set("affected_files", len(files_with_edits))
    meta.set("total_edits", len(edits))
    meta.set("old_name", old_name)
    meta.set("new_name", new_name)

    result = {
        "symbol": {
            "symbol_id": symbol_id,
            "name": old_name,
            "kind": target.kind,
            "file": target_file_path,
            "line_start": target.line_start,
            "line_end": target.line_end,
        },
        "new_name": new_name,
        "edits": edits,
        "_hints": {
            "edit": hint_reads,
        },
    }

    return wrap_response(result, meta.build())
