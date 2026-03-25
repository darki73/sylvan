"""Blast radius analysis -- estimate impact of changing a symbol."""

import re
from collections import deque

from sylvan.database.orm import Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.database.orm.runtime.connection_manager import get_backend


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
    depth_reached = 0

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
        occurrences = len(re.findall(r"\b" + re.escape(target_name) + r"\b", text))

        entry = {
            "file": file_row["path"],
            "depth": depth,
            "occurrences": occurrences,
        }

        file_symbols = await (
            Symbol.where(file_id=file_id).select("symbol_id", "name", "kind", "line_start").limit(10).get()
        )
        entry["symbols"] = [
            {"symbol_id": s.symbol_id, "name": s.name, "kind": s.kind, "line_start": s.line_start} for s in file_symbols
        ]

        if occurrences > 0:
            confirmed.append(entry)
        else:
            potential.append(entry)

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

    return {
        "symbol": {
            "symbol_id": symbol_id,
            "name": target_name,
            "kind": target.kind,
            "file": target_file_path,
        },
        "confirmed": confirmed,
        "potential": potential,
        "depth_reached": depth_reached,
        "total_affected": len(confirmed) + len(potential),
    }
