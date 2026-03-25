"""MCP tool: get_symbol_diff -- compare symbols between git commits."""

from __future__ import annotations

from pathlib import Path

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response


async def _current_symbols_for_repo(
    repo_id: int,
    file_path: str | None,
) -> dict[str, list[dict]]:
    """Load current symbols grouped by file path.

    Args:
        repo_id: Database ID of the repository.
        file_path: Optional file path filter.

    Returns:
        Dict mapping file paths to lists of symbol dicts with name, kind,
        qualified_name, signature, and content_hash.
    """
    query = (
        Symbol.query()
        .select(
            "symbols.name",
            "symbols.kind",
            "symbols.qualified_name",
            "symbols.signature",
            "symbols.content_hash",
            "files.path AS file_path",
        )
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo_id)
    )
    if file_path:
        query = query.where("files.path", file_path)

    rows = await query.get()

    by_file: dict[str, list[dict]] = {}
    for row in rows:
        fp = row.file_path
        by_file.setdefault(fp, []).append(
            {
                "name": row.name,
                "kind": row.kind,
                "qualified_name": row.qualified_name,
                "signature": row.signature or "",
                "content_hash": row.content_hash or "",
            }
        )
    return by_file


def _parse_old_file(content: str, file_path: str, language: str) -> list[dict]:
    """Parse old file content and return symbol dicts.

    Args:
        content: Source code text from the old commit.
        file_path: Relative file path.
        language: Language identifier.

    Returns:
        List of symbol dicts with name, kind, qualified_name, signature,
        and content_hash.
    """
    from sylvan.indexing.source_code.extractor import parse_file

    symbols = parse_file(content, file_path, language)
    return [
        {
            "name": s.name,
            "kind": s.kind,
            "qualified_name": s.qualified_name,
            "signature": s.signature or "",
            "content_hash": s.content_hash or "",
        }
        for s in symbols
    ]


def _diff_symbols(
    old_syms: list[dict],
    new_syms: list[dict],
) -> dict[str, list[dict]]:
    """Compute added, removed, and changed symbols between two snapshots.

    Args:
        old_syms: Symbol dicts from the old commit.
        new_syms: Symbol dicts from the current index.

    Returns:
        Dict with ``added``, ``removed``, ``changed``, and ``unchanged``
        lists of symbol summaries.
    """
    old_map = {(s["qualified_name"], s["kind"]): s for s in old_syms}
    new_map = {(s["qualified_name"], s["kind"]): s for s in new_syms}

    old_keys = set(old_map)
    new_keys = set(new_map)

    added = [
        {"qualified_name": k[0], "kind": k[1], "signature": new_map[k]["signature"]}
        for k in sorted(new_keys - old_keys)
    ]
    removed = [
        {"qualified_name": k[0], "kind": k[1], "signature": old_map[k]["signature"]}
        for k in sorted(old_keys - new_keys)
    ]

    changed = []
    unchanged_count = 0
    for k in sorted(old_keys & new_keys):
        old_s = old_map[k]
        new_s = new_map[k]
        if old_s["content_hash"] != new_s["content_hash"]:
            entry: dict = {"qualified_name": k[0], "kind": k[1]}
            if old_s["signature"] != new_s["signature"]:
                entry["old_signature"] = old_s["signature"]
                entry["new_signature"] = new_s["signature"]
            else:
                entry["signature"] = new_s["signature"]
            changed.append(entry)
        else:
            unchanged_count += 1

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": unchanged_count,
    }


@log_tool_call
async def get_symbol_diff(
    repo: str,
    commit: str = "HEAD~1",
    file_path: str | None = None,
    max_files: int = 50,
) -> dict:
    """Compare current symbols against a previous git commit.

    Extracts symbols from old file versions via ``git show`` and tree-sitter,
    then diffs against the current index to find added, removed, and changed
    symbols.

    Args:
        repo: Repository name.
        commit: Git ref to compare against (default ``HEAD~1``).
        file_path: Optional file path filter.
        max_files: Maximum number of files to diff.

    Returns:
        Tool response dict with per-file diffs and summary counts.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = MetaBuilder()
    max_files = clamp(max_files, 1, 200)
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if not repo_obj:
        raise RepoNotFoundError(f"Repository '{repo}' is not indexed.", repo_name=repo, _meta=meta.build())

    source_root = Path(repo_obj.source_path) if repo_obj.source_path else None
    if source_root is None or not source_root.exists():
        return wrap_response(
            {"error": "source_unavailable", "detail": "Repository source path is not available on disk."},
            meta.build(),
        )

    current_by_file = await _current_symbols_for_repo(repo_obj.id, file_path)

    # Determine which files to diff
    if file_path:
        file_paths_to_diff = [file_path] if file_path in current_by_file else []
        # Also check if file existed in old commit but not current
        if not file_paths_to_diff:
            file_paths_to_diff = [file_path]
    else:
        files = (
            await FileRecord.where(repo_id=repo_obj.id)
            .where_not_null("language")
            .order_by("path")
            .limit(max_files)
            .get()
        )
        file_paths_to_diff = [f.path for f in files]

    from sylvan.git import run_git
    from sylvan.indexing.source_code.language_registry import get_language_for_extension

    file_diffs = []
    total_added = 0
    total_removed = 0
    total_changed = 0
    total_unchanged = 0
    files_compared = 0

    for fp in file_paths_to_diff[:max_files]:
        ext = Path(fp).suffix
        language = get_language_for_extension(ext)
        if not language:
            continue

        old_content = run_git(source_root, ["show", f"{commit}:{fp}"])
        old_syms = _parse_old_file(old_content, fp, language) if old_content else []

        new_syms = current_by_file.get(fp, [])

        if not old_syms and not new_syms:
            continue

        diff = _diff_symbols(old_syms, new_syms)
        files_compared += 1

        if diff["added"] or diff["removed"] or diff["changed"]:
            file_diffs.append({"file": fp, **diff})

        total_added += len(diff["added"])
        total_removed += len(diff["removed"])
        total_changed += len(diff["changed"])
        total_unchanged += diff["unchanged_count"]

    summary = {
        "added": total_added,
        "removed": total_removed,
        "changed": total_changed,
        "unchanged": total_unchanged,
    }

    meta.set("files_compared", files_compared)
    meta.set("files_with_changes", len(file_diffs))
    meta.set("commit", commit)

    return wrap_response(
        {"repo": repo, "commit": commit, "summary": summary, "file_diffs": file_diffs},
        meta.build(),
    )
