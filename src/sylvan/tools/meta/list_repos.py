"""MCP tool: list_repos -- list all indexed repositories."""

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def list_repos() -> dict:
    """List all indexed repositories with summary statistics.

    Returns:
        Tool response dict with ``repos`` list and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    repos = await Repo.all().order_by("name").get()
    result = []
    for r in repos:
        file_count = await FileRecord.where(repo_id=r.id).count()
        symbol_count = await (Symbol.query()
                       .join("files", "files.id = symbols.file_id")
                       .where("files.repo_id", r.id)
                       .count())
        result.append({
            "id": r.id,
            "name": r.name,
            "source_path": r.source_path,
            "github_url": r.github_url,
            "indexed_at": r.indexed_at,
            "git_head": r.git_head,
            "file_count": file_count,
            "symbol_count": symbol_count,
        })
    meta.set("count", len(result))
    return wrap_response({"repos": result}, meta.build())
