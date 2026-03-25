"""MCP tool: suggest_queries -- intelligent query suggestions for exploring a repo."""

from sylvan.context import get_context
from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


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
            "query": f"get_symbol for {entry_point.name} in {getattr(entry_point, 'path', '')}",
            "reason": "Entry point / main function",
            "tool": "get_symbol",
        }
        for entry_point in entry_symbols
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


@log_tool_call
async def suggest_queries(repo: str) -> dict:
    """Suggest useful queries for exploring an indexed repository.

    Based on:
    - Repository structure (top symbols, entry points, key files)
    - Session context (what the agent has already explored)
    - Common exploration patterns

    Args:
        repo: Repository name.

    Returns:
        Tool response dict with ``suggestions`` list and ``_meta`` envelope.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = MetaBuilder()
    ctx = get_context()
    session = ctx.session
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

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

    meta.set("suggestion_count", len(suggestions))
    return wrap_response({"suggestions": suggestions}, meta.build())
