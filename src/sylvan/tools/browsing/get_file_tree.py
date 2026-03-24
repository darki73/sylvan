"""MCP tool: get_file_tree -- compact directory tree for a repo."""

from sylvan.database.orm import FileRecord, Repo
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, check_staleness, ensure_orm, log_tool_call, wrap_response


def _build_tree_structure(files: list) -> dict:
    """Build a nested dict tree from flat file paths.

    Leaf nodes are ``(language, symbol_count)`` tuples; directory nodes
    are nested dicts.

    Args:
        files: ORM file record list, each with ``.path``, ``.language``,
            and ``symbols_count``.

    Returns:
        Nested dict representing the directory structure.
    """
    root: dict = {}
    for file_record in files:
        parts = file_record.path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (file_record.language or "", getattr(file_record, "symbols_count", 0))
    return root


@log_tool_call
async def get_file_tree(repo: str, max_depth: int = 3) -> dict:
    """Get a compact directory tree for an indexed repository.

    Returns an indented text tree (like the ``tree`` command) instead of
    deeply nested JSON -- much more token-efficient for LLM consumption.
    Directories beyond *max_depth* are collapsed with file counts.

    Args:
        repo: Repository name.
        max_depth: Maximum directory depth to expand (1--10).

    Returns:
        Tool response dict with ``tree`` string and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

    max_depth = min(max(max_depth, 1), 10)

    files = await (FileRecord.where(repo_id=repo_obj.id)
             .with_count("symbols")
             .order_by("path")
             .get())

    root = _build_tree_structure(files)

    lines: list[str] = [f"{repo}/"]
    truncated = _render_tree(root, lines, prefix="", depth=0, max_depth=max_depth)

    meta.set("repo", repo)
    meta.set("files", len(files))
    meta.set("max_depth", max_depth)
    if truncated:
        meta.set("truncated", True)

    response = wrap_response({"tree": "\n".join(lines)}, meta.build())
    await check_staleness(repo_obj.id, response)
    return response


def _render_tree(
    node: dict,
    lines: list[str],
    prefix: str,
    depth: int,
    max_depth: int,
) -> bool:
    """Render tree nodes as indented text lines.

    Args:
        node: Current directory dict (files are tuples, dirs are dicts).
        lines: Accumulator list of rendered text lines.
        prefix: Indentation prefix for the current level.
        depth: Current nesting depth (zero-based).
        max_depth: Maximum depth before collapsing.

    Returns:
        True if any branch was truncated due to *max_depth*.
    """
    truncated = False
    entries = sorted(node.items(), key=lambda x: (isinstance(x[1], tuple), x[0]))

    for i, (name, value) in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        child_prefix = prefix + ("    " if is_last else "\u2502   ")

        if isinstance(value, tuple):
            lang, syms = value
            tag = f"  [{lang}, {syms} sym]" if lang else ""
            lines.append(f"{prefix}{connector}{name}{tag}")
        elif depth >= max_depth:
            count = _count_files(value)
            lines.append(f"{prefix}{connector}{name}/  \u2026 {count} files")
            truncated = True
        else:
            lines.append(f"{prefix}{connector}{name}/")
            if _render_tree(value, lines, child_prefix, depth + 1, max_depth):
                truncated = True
    return truncated


def _count_files(node: dict) -> int:
    """Count total files in a subtree.

    Args:
        node: A directory dict node from the tree.

    Returns:
        Total number of file leaves in the subtree.
    """
    count = 0
    for value in node.values():
        if isinstance(value, tuple):
            count += 1
        else:
            count += _count_files(value)
    return count
