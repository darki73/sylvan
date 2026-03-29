"""Meta service - suggestions, logs, and scaffolding."""

from __future__ import annotations

from pathlib import Path

from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.error_codes import RepoNotFoundError


async def suggest_queries(repo: str) -> dict:
    """Suggest useful queries for exploring an indexed repository.

    Based on repository structure - top symbols, entry points, key files,
    and session context.

    Args:
        repo: Repository name.

    Returns:
        Dict with suggestions list.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    from sylvan.context import get_context

    ctx = get_context()
    session = ctx.session

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo)

    repo_id = repo_obj.id
    suggestions = []

    suggestions.extend(await _find_entry_points(repo_id))
    suggestions.extend(await _find_popular_classes(repo_id))

    structure_suggestion = await _suggest_structure_exploration(repo_id, repo)
    if structure_suggestion:
        suggestions.append(structure_suggestion)

    doc_suggestion = await _suggest_documentation(repo_id, repo)
    if doc_suggestion:
        suggestions.append(doc_suggestion)

    unexplored_suggestion = await _suggest_unexplored_files(repo_id, session)
    if unexplored_suggestion:
        suggestions.append(unexplored_suggestion)

    return {"suggestions": suggestions}


async def _find_entry_points(repo_id: int) -> list[dict]:
    """Find well-known entry point functions (main, app, run, etc.).

    Args:
        repo_id: Database ID of the repository.

    Returns:
        List of suggestion dicts for discovered entry points.
    """
    entry_names = ["main", "app", "run", "start", "cli", "server"]
    entry_symbols = await (
        Symbol.query()
        .select("symbols.name", "symbols.kind", "f.path")
        .join("files f", "f.id = symbols.file_id")
        .where("f.repo_id", repo_id)
        .where("symbols.kind", "function")
        .where_in("symbols.name", entry_names)
        .limit(5)
        .get()
    )
    return [
        {
            "query": f"get_symbol for {ep.name} in {getattr(ep, 'path', '')}",
            "reason": "Entry point / main function",
            "tool": "get_symbol",
        }
        for ep in entry_symbols
    ]


async def _find_popular_classes(repo_id: int) -> list[dict]:
    """Find the most popular classes ranked by method count.

    Args:
        repo_id: Database ID of the repository.

    Returns:
        List of suggestion dicts for top classes.
    """
    popular_classes = await (
        Symbol.query()
        .select("symbols.name", "symbols.symbol_id", "COUNT(c.id) as method_count")
        .join("files f", "f.id = symbols.file_id")
        .left_join("symbols c", "c.parent_symbol_id = symbols.symbol_id")
        .where("f.repo_id", repo_id)
        .where("symbols.kind", "class")
        .group_by("symbols.symbol_id")
        .order_by("method_count", "DESC")
        .limit(5)
        .get()
    )
    return [
        {
            "query": cls.name,
            "reason": f"Key class ({getattr(cls, 'method_count', 0)} methods)",
            "tool": "search_symbols",
        }
        for cls in popular_classes
    ]


async def _suggest_structure_exploration(repo_id: int, repo: str) -> dict | None:
    """Suggest exploring the file tree if multiple languages are present.

    Args:
        repo_id: Database ID of the repository.
        repo: Repository display name.

    Returns:
        A suggestion dict, or None if no structure suggestion applies.
    """
    languages = await FileRecord.where(repo_id=repo_id).where_not_null("language").group_by("language").count()
    if languages:
        lang_names = ", ".join(languages.keys()) if isinstance(languages, dict) else ""
        return {
            "query": f"get_file_tree for {repo}",
            "reason": f"Explore structure ({lang_names})",
            "tool": "get_file_tree",
        }
    return None


async def _suggest_documentation(repo_id: int, repo: str) -> dict | None:
    """Suggest browsing documentation if sections exist.

    Args:
        repo_id: Database ID of the repository.
        repo: Repository display name.

    Returns:
        A suggestion dict, or None if no documentation exists.
    """
    doc_count = await (
        Section.query().join("files", "files.id = sections.file_id").where("files.repo_id", repo_id).count()
    )
    if doc_count > 0:
        return {
            "query": f"get_toc for {repo}",
            "reason": f"Browse documentation ({doc_count} sections)",
            "tool": "get_toc",
        }
    return None


async def _suggest_unexplored_files(repo_id: int, session: object) -> dict | None:
    """Suggest an unexplored file based on the current session's working set.

    Args:
        repo_id: Database ID of the repository.
        session: The session tracker instance.

    Returns:
        A suggestion dict, or None if no unexplored files remain.
    """
    seen_files = set(session.get_working_files())
    if not seen_files:
        return None
    all_file_paths = await FileRecord.where(repo_id=repo_id).order_by("path").pluck("path")
    unseen = [p for p in all_file_paths if p not in seen_files]
    if unseen:
        return {
            "query": f"get_file_outline for {unseen[0]}",
            "reason": f"Unexplored file ({len(unseen)} files not yet visited)",
            "tool": "get_file_outline",
        }
    return None


async def get_logs(
    lines: int = 50,
    from_start: bool = False,
    offset: int = 0,
) -> dict:
    """Retrieve log entries from the sylvan server log.

    Args:
        lines: Number of lines to return. Clamped to 1-500.
        from_start: If True, read from the beginning instead of the end.
        offset: Skip this many lines before reading.

    Returns:
        Dict with entries list and metadata.
    """
    from sylvan.logging import _get_log_dir

    lines = max(1, min(lines, 500))
    log_file = _get_log_dir() / "sylvan.log"

    if not log_file.exists():
        return {"entries": [], "message": "No log file found."}

    try:
        all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as error:
        return {"entries": [], "error": f"Failed to read log file: {error}"}

    total = len(all_lines)

    if from_start:
        result = all_lines[offset : offset + lines]
    else:
        end = total - offset
        start = max(0, end - lines)
        result = all_lines[start:end] if end > 0 else []

    return {
        "entries": result,
        "total_lines": total,
        "returned_lines": len(result),
        "offset": offset,
        "from_start": from_start,
        "log_file": str(log_file),
    }


async def scaffold(
    repo: str,
    agent: str = "claude",
    root: str | None = None,
) -> dict:
    """Generate the sylvan/ project context directory and agent instructions.

    Args:
        repo: Indexed repo name.
        agent: Agent format ("claude", "cursor", "copilot", "generic").
        root: Override project root path.

    Returns:
        Dict with scaffold status and files_created count.
    """
    from sylvan.scaffold.generator import async_scaffold_project

    return await async_scaffold_project(
        repo,
        agent=agent,
        project_root=Path(root) if root else None,
    )
