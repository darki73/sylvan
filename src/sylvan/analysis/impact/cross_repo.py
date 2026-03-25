"""Cross-repo analysis -- resolve imports and blast radius across repo boundaries."""

import re
from collections import deque

from sylvan.database.orm.models.blob import Blob
from sylvan.database.orm.runtime.connection_manager import get_backend


async def resolve_cross_repo_imports(
    repo_ids: list[int],
) -> int:
    """Resolve file imports that cross repo boundaries.

    For each unresolved import in any of the given repos, try to match the
    specifier against files in the other repos. Updates resolved_file_id
    in the file_imports table.

    Args:
        repo_ids: List of repository database IDs to scan.

    Returns:
        Number of cross-repo imports resolved.
    """
    backend = get_backend()

    file_lookup: dict[str, int] = {}
    for row in await backend.fetch_all(
        f"""SELECT id, path, repo_id FROM files
           WHERE repo_id IN ({",".join("?" * len(repo_ids))})""",
        repo_ids,
    ):
        fid = row["id"]
        path = row["path"]
        file_lookup[path] = fid
        filename = path.rsplit("/", 1)[-1]
        file_lookup.setdefault(filename, fid)
        stem = filename.rsplit(".", 1)[0]
        file_lookup.setdefault(stem, fid)
        dotpath = path.replace("/", ".").rsplit(".", 1)[0]
        file_lookup.setdefault(dotpath, fid)

    unresolved = await backend.fetch_all(
        f"""SELECT fi.id, fi.specifier, fi.file_id, f.repo_id
           FROM file_imports fi
           JOIN files f ON f.id = fi.file_id
           WHERE f.repo_id IN ({",".join("?" * len(repo_ids))})
           AND fi.resolved_file_id IS NULL""",
        repo_ids,
    )

    resolved_count = 0
    for imp in unresolved:
        spec = imp["specifier"]
        source_repo_id = imp["repo_id"]

        candidates = []

        if spec in file_lookup:
            target_fid = file_lookup[spec]
            target_repo = await backend.fetch_one("SELECT repo_id FROM files WHERE id = ?", [target_fid])
            if target_repo and target_repo["repo_id"] != source_repo_id:
                candidates.append(target_fid)

        stem = spec.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if stem in file_lookup and not candidates:
            target_fid = file_lookup[stem]
            target_repo = await backend.fetch_one("SELECT repo_id FROM files WHERE id = ?", [target_fid])
            if target_repo and target_repo["repo_id"] != source_repo_id:
                candidates.append(target_fid)

        dotpath = spec.replace(".", "/")
        for suffix in ("", ".py", ".ts", ".js", ".go"):
            key = dotpath + suffix
            if key in file_lookup and not candidates:
                target_fid = file_lookup[key]
                target_repo = await backend.fetch_one("SELECT repo_id FROM files WHERE id = ?", [target_fid])
                if target_repo and target_repo["repo_id"] != source_repo_id:
                    candidates.append(target_fid)

        if candidates:
            await backend.execute(
                "UPDATE file_imports SET resolved_file_id = ? WHERE id = ?",
                [candidates[0], imp["id"]],
            )
            resolved_count += 1

    if resolved_count:
        await backend.commit()
    return resolved_count


async def cross_repo_blast_radius(
    symbol_id: str,
    repo_ids: list[int],
    max_depth: int = 3,
) -> dict:
    """Blast radius analysis that crosses repo boundaries.

    Like get_blast_radius but follows imports across all repos in the workspace.

    Args:
        symbol_id: Unique identifier of the target symbol.
        repo_ids: List of repository database IDs to scan.
        max_depth: Maximum BFS traversal depth.

    Returns:
        Dictionary with "symbol", "confirmed", "potential",
        "depth_reached", "total_affected", "cross_repo_affected",
        and "repos_scanned" keys. Returns an error dict if the
        symbol is not found.
    """
    backend = get_backend()

    target = await backend.fetch_one(
        """SELECT s.*, f.path as file_path, f.repo_id, f.content_hash,
                  r.name as repo_name
           FROM symbols s
           JOIN files f ON f.id = s.file_id
           JOIN repos r ON r.id = f.repo_id
           WHERE s.symbol_id = ?""",
        [symbol_id],
    )

    if target is None:
        return {"error": "symbol_not_found", "symbol_id": symbol_id}

    target_dict = dict(target)
    target_name = target_dict["name"]
    target_file_id = target_dict["file_id"]

    visited_files: set[int] = {target_file_id}
    queue: deque[tuple[int, int]] = deque()

    repo_filter = ",".join("?" * len(repo_ids))
    importers = await backend.fetch_all(
        f"""SELECT DISTINCT fi.file_id
           FROM file_imports fi
           JOIN files f ON f.id = fi.file_id
           WHERE f.repo_id IN ({repo_filter})
           AND (fi.resolved_file_id = ? OR fi.specifier LIKE ?)""",
        [*repo_ids, target_file_id, f"%{target_dict['file_path'].rsplit('/', 1)[-1].rsplit('.', 1)[0]}%"],
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

        file_row = await backend.fetch_one(
            """SELECT f.path, f.content_hash, r.name as repo_name
               FROM files f JOIN repos r ON r.id = f.repo_id
               WHERE f.id = ?""",
            [file_id],
        )
        if file_row is None:
            continue

        content = await Blob.get(file_row["content_hash"])
        if content is None:
            continue

        text = content.decode("utf-8", errors="replace")
        occurrences = len(re.findall(r"\b" + re.escape(target_name) + r"\b", text))

        entry = {
            "file": file_row["path"],
            "repo": file_row["repo_name"],
            "depth": depth,
            "occurrences": occurrences,
            "cross_repo": file_row["repo_name"] != target_dict["repo_name"],
        }

        if occurrences > 0:
            confirmed.append(entry)
        else:
            potential.append(entry)

        if depth < max_depth:
            next_importers = await backend.fetch_all(
                f"""SELECT DISTINCT fi2.file_id FROM file_imports fi2
                   JOIN files f2 ON f2.id = fi2.file_id
                   WHERE f2.repo_id IN ({repo_filter})
                   AND fi2.resolved_file_id = ?""",
                [*repo_ids, file_id],
            )
            for ni in next_importers:
                if ni["file_id"] not in visited_files:
                    queue.append((ni["file_id"], depth + 1))
                    visited_files.add(ni["file_id"])

    return {
        "symbol": {
            "symbol_id": target_dict["symbol_id"],
            "name": target_name,
            "kind": target_dict["kind"],
            "file": target_dict["file_path"],
            "repo": target_dict["repo_name"],
        },
        "confirmed": confirmed,
        "potential": potential,
        "depth_reached": depth_reached,
        "total_affected": len(confirmed) + len(potential),
        "cross_repo_affected": sum(1 for c in confirmed + potential if c.get("cross_repo")),
        "repos_scanned": len(repo_ids),
    }
