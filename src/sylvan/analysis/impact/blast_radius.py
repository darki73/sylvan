"""Blast radius analysis -- estimate impact of changing a symbol."""

import re
from collections import deque

from sylvan.database.orm import Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.database.orm.runtime.connection_manager import get_backend

_MAX_CONFIRMED = 25
_MAX_POTENTIAL = 25


async def get_blast_radius(
    symbol_id: str,
    max_depth: int = 3,
) -> dict:
    """Estimate the blast radius of changing a symbol.

    Uses BFS through the reference graph + text confirmation.

    Args:
        symbol_id: Unique identifier of the target symbol.
        max_depth: Maximum BFS traversal depth.

    Returns:
        Dictionary with "symbol", "confirmed", "potential",
        "depth_reached", and "total_affected" keys. Returns an error
        dict if the symbol is not found.
    """
    backend = get_backend()

    target = await (
        Symbol.query()
        .select("symbols.*", "f.path as file_path", "f.content_hash", "f.repo_id")
        .join("files f", "f.id = symbols.file_id")
        .where("symbols.symbol_id", symbol_id)
        .first()
    )

    if target is None:
        return {"error": "symbol_not_found", "symbol_id": symbol_id}

    target_name = target.name
    target_file_id = target.file_id
    target_file_path = getattr(target, "file_path", "")
    repo_id = getattr(target, "repo_id", None)

    visited_files: set[int] = {target_file_id}
    queue: deque[tuple[int, int]] = deque()  # (file_id, depth)

    importers = await backend.fetch_all(
        """SELECT DISTINCT fi.file_id
           FROM file_imports fi
           JOIN files f ON f.id = fi.file_id
           WHERE f.repo_id = ?
           AND (fi.resolved_file_id = ?
                OR fi.specifier LIKE ?)""",
        [repo_id, target_file_id, f"%{target_file_path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}%"],
    )

    for imp in importers:
        fid = imp["file_id"]
        if fid not in visited_files:
            queue.append((fid, 1))
            visited_files.add(fid)

    confirmed = []
    potential = []
    total_confirmed = 0
    total_potential = 0
    depth_reached = 0
    name_pattern = re.compile(r"\b" + re.escape(target_name) + r"\b")

    while queue:
        file_id, depth = queue.popleft()
        depth_reached = max(depth_reached, depth)

        if depth > max_depth:
            continue

        file_row = await backend.fetch_one("SELECT path, content_hash FROM files WHERE id = ?", [file_id])
        if file_row is None:
            continue

        content = await Blob.get(file_row["content_hash"])
        if content is None:
            continue

        text = content.decode("utf-8", errors="replace")
        occurrences = len(name_pattern.findall(text))

        if occurrences > 0:
            total_confirmed += 1
            if len(confirmed) < _MAX_CONFIRMED:
                file_symbols = await (
                    Symbol.where(file_id=file_id).select("symbol_id", "name", "kind", "line_start").get()
                )
                matching = [
                    {"symbol_id": s.symbol_id, "name": s.name, "kind": s.kind, "line_start": s.line_start}
                    for s in file_symbols
                    if name_pattern.search(s.name) or s.name == target_name
                ]
                if not matching:
                    matching = [
                        {"symbol_id": s.symbol_id, "name": s.name, "kind": s.kind, "line_start": s.line_start}
                        for s in file_symbols[:5]
                    ]
                confirmed.append(
                    {
                        "file": file_row["path"],
                        "depth": depth,
                        "occurrences": occurrences,
                        "symbols": matching,
                    }
                )
        else:
            total_potential += 1
            if len(potential) < _MAX_POTENTIAL:
                potential.append(
                    {
                        "file": file_row["path"],
                        "depth": depth,
                        "occurrences": 0,
                        "symbols": [],
                    }
                )

        if depth < max_depth:
            next_importers = await backend.fetch_all(
                """SELECT DISTINCT fi.file_id FROM file_imports fi
                   JOIN files f ON f.id = fi.file_id
                   WHERE f.repo_id = ? AND fi.resolved_file_id = ?""",
                [repo_id, file_id],
            )
            for ni in next_importers:
                nfid = ni["file_id"]
                if nfid not in visited_files:
                    queue.append((nfid, depth + 1))
                    visited_files.add(nfid)

    result: dict = {
        "symbol": {
            "symbol_id": symbol_id,
            "name": target_name,
            "kind": target.kind,
            "file": target_file_path,
        },
        "confirmed": confirmed,
        "potential": potential,
        "depth_reached": depth_reached,
        "total_affected": total_confirmed + total_potential,
    }
    if total_confirmed > _MAX_CONFIRMED or total_potential > _MAX_POTENTIAL:
        result["truncated"] = {
            "confirmed_total": total_confirmed,
            "confirmed_shown": len(confirmed),
            "potential_total": total_potential,
            "potential_shown": len(potential),
        }
    return result
