"""Git service - git context, recent changes, and symbol diff operations."""

from __future__ import annotations

from pathlib import Path

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.error_codes import RepoNotFoundError, SymbolNotFoundError


class GitService:
    """Service for git-related code intelligence operations."""

    async def context(
        self,
        repo: str,
        file_path: str | None = None,
        symbol_id: str | None = None,
    ) -> dict:
        """Get git context for a file or symbol: blame, change frequency, recent commits.

        Args:
            repo: Repository name.
            file_path: File to get git context for.
            symbol_id: Symbol to get blame for (alternative to file_path).

        Returns:
            Dict with blame/commit data.

        Raises:
            RepoNotFoundError: If the repository is not indexed.
        """
        repo_obj = await Repo.where(name=repo).first()
        if repo_obj is None or not repo_obj.source_path:
            raise RepoNotFoundError(repo=repo)

        root = Path(repo_obj.source_path)

        if symbol_id:
            return await _symbol_git_context(root, symbol_id)
        elif file_path:
            return _file_git_context(root, file_path)
        else:
            return {"error": "provide file_path or symbol_id"}

    async def recent_changes(
        self,
        repo: str,
        commits: int = 5,
        file_path: str | None = None,
    ) -> dict:
        """Show what changed in the last N commits at the file level.

        Args:
            repo: Repository name.
            commits: Number of commits to look back (default 5, max 100).
            file_path: Optional file path filter to restrict results.

        Returns:
            Dict with changed files and summary.

        Raises:
            RepoNotFoundError: If the repository is not indexed.
        """
        commits = min(max(commits, 1), 100)

        repo_obj = await Repo.where(name=repo).first()
        if not repo_obj:
            raise RepoNotFoundError(f"Repository '{repo}' is not indexed.", repo_name=repo)

        source_root = Path(repo_obj.source_path) if repo_obj.source_path else None
        if source_root is None or not source_root.exists():
            return {"error": "source_unavailable", "detail": "Repository source path is not available on disk."}

        from sylvan.git.diff import get_changed_files, get_commit_log

        changed = get_changed_files(source_root, f"HEAD~{commits}")

        if file_path:
            changed = [f for f in changed if f == file_path]

        files_changed: list[dict] = []

        for fp in changed:
            file_rec = await FileRecord.where(repo_id=repo_obj.id, path=fp).first()
            if file_rec is None:
                continue

            symbol_count = await Symbol.where(file_id=file_rec.id).count()
            log_entries = get_commit_log(source_root, file_path=fp, max_count=1)
            last_commit = log_entries[0] if log_entries else None

            entry: dict = {
                "file": fp,
                "language": file_rec.language,
                "symbol_count": symbol_count,
            }
            if last_commit:
                entry["last_commit"] = {
                    "hash": last_commit["hash"][:8],
                    "author": last_commit["author"],
                    "date": last_commit["date"],
                    "message": last_commit["message"],
                }

            files_changed.append(entry)

        return {
            "repo": repo,
            "commits": commits,
            "files_changed": files_changed,
            "summary": f"{len(files_changed)} indexed files changed across last {commits} commits",
        }

    async def symbol_diff(
        self,
        repo: str,
        commit: str = "HEAD~1",
        file_path: str | None = None,
        max_files: int = 50,
    ) -> dict:
        """Compare current symbols against a previous git commit.

        Args:
            repo: Repository name.
            commit: Git ref to compare against (default HEAD~1).
            file_path: Optional file path filter.
            max_files: Maximum number of files to diff.

        Returns:
            Dict with per-file diffs and summary counts.

        Raises:
            RepoNotFoundError: If the repository is not indexed.
        """
        from sylvan.services.analysis import _diff_symbols

        max_files = min(max(max_files, 1), 200)

        repo_obj = await Repo.where(name=repo).first()
        if not repo_obj:
            raise RepoNotFoundError(f"Repository '{repo}' is not indexed.", repo_name=repo)

        source_root = Path(repo_obj.source_path) if repo_obj.source_path else None
        if source_root is None or not source_root.exists():
            return {"error": "source_unavailable", "detail": "Repository source path is not available on disk."}

        current_by_file = await _current_symbols_for_repo(repo_obj.id, file_path)

        if file_path:
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

        return {
            "repo": repo,
            "commit": commit,
            "summary": {
                "added": total_added,
                "removed": total_removed,
                "changed": total_changed,
                "unchanged": total_unchanged,
            },
            "file_diffs": file_diffs,
            "files_compared": files_compared,
            "files_with_changes": len(file_diffs),
        }


async def _symbol_git_context(root: Path, symbol_id: str) -> dict:
    """Get git blame for a specific symbol.

    Args:
        root: Absolute path to the repository root.
        symbol_id: The symbol identifier to look up.

    Returns:
        Dict with blame and change frequency data.

    Raises:
        SymbolNotFoundError: If the symbol does not exist.
    """
    symbol = await Symbol.where(symbol_id=symbol_id).with_("file").first()
    if symbol is None:
        raise SymbolNotFoundError(symbol_id=symbol_id)

    file_rec = symbol.file
    file_path = file_rec.path if file_rec else ""

    from sylvan.git.blame import blame_symbol, get_change_frequency

    blame = blame_symbol(root, file_path, symbol.line_start, symbol.line_end or symbol.line_start)
    freq = get_change_frequency(root, file_path)

    return {
        "symbol_id": symbol_id,
        "file": file_path,
        "blame": blame,
        "change_frequency": freq,
    }


def _file_git_context(root: Path, file_path: str) -> dict:
    """Get git context for a file: recent commits and change frequency.

    Args:
        root: Absolute path to the repository root.
        file_path: Relative file path within the repo.

    Returns:
        Dict with commit history and change frequency data.
    """
    from sylvan.git.blame import get_change_frequency
    from sylvan.git.diff import get_commit_log

    commits = get_commit_log(root, file_path=file_path, max_count=10)
    freq = get_change_frequency(root, file_path)

    return {
        "file": file_path,
        "change_frequency": freq,
        "recent_commits": commits,
    }


async def _current_symbols_for_repo(
    repo_id: int,
    file_path: str | None,
) -> dict[str, list[dict]]:
    """Load current symbols grouped by file path.

    Args:
        repo_id: Database ID of the repository.
        file_path: Optional file path filter.

    Returns:
        Dict mapping file paths to lists of symbol dicts.
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
        List of symbol dicts.
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
