"""MCP tool: get_git_context -- git blame, change history, branch diffs."""

from pathlib import Path

from sylvan.database.orm import Repo, Symbol
from sylvan.error_codes import RepoNotFoundError, SymbolNotFoundError
from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def get_git_context(
    repo: str,
    file_path: str | None = None,
    symbol_id: str | None = None,
) -> dict:
    """Get git context for a file or symbol: blame, change frequency, recent commits.

    Args:
        repo: Repository name.
        file_path: File to get git context for.
        symbol_id: Symbol to get blame for (alternative to *file_path*).

    Returns:
        Tool response dict with blame/commit data and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None or not repo_obj.source_path:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

    root = Path(repo_obj.source_path)

    if symbol_id:
        return await _symbol_git_context(root, symbol_id, meta)
    elif file_path:
        return _file_git_context(root, file_path, meta)
    else:
        return wrap_response(
            {"error": "provide file_path or symbol_id"},
            meta.build(),
        )


async def _symbol_git_context(root: Path, symbol_id: str, meta: MetaBuilder) -> dict:
    """Get git blame for a specific symbol.

    Args:
        root: Absolute path to the repository root.
        symbol_id: The symbol identifier to look up.
        meta: The meta builder for the response envelope.

    Returns:
        Tool response dict with blame and change frequency data.
    """
    symbol = await Symbol.where(symbol_id=symbol_id).with_("file").first()

    if symbol is None:
        raise SymbolNotFoundError(symbol_id=symbol_id, _meta=meta.build())

    file_rec = symbol.file
    file_path = file_rec.path if file_rec else ""

    from sylvan.git.blame import blame_symbol

    blame = blame_symbol(root, file_path, symbol.line_start, symbol.line_end or symbol.line_start)

    from sylvan.git.blame import get_change_frequency

    freq = get_change_frequency(root, file_path)

    result = {
        "symbol_id": symbol_id,
        "file": file_path,
        "blame": blame,
        "change_frequency": freq,
    }
    return wrap_response(result, meta.build())


def _file_git_context(root: Path, file_path: str, meta: MetaBuilder) -> dict:
    """Get git context for a file: recent commits and change frequency.

    Args:
        root: Absolute path to the repository root.
        file_path: Relative file path within the repo.
        meta: The meta builder for the response envelope.

    Returns:
        Tool response dict with commit history and change frequency data.
    """
    from sylvan.git.blame import get_change_frequency
    from sylvan.git.diff import get_commit_log

    commits = get_commit_log(root, file_path=file_path, max_count=10)
    freq = get_change_frequency(root, file_path)

    result = {
        "file": file_path,
        "change_frequency": freq,
        "recent_commits": commits,
    }
    return wrap_response(result, meta.build())
