"""MCP tool: remove_repo -- delete an indexed repository and all its data."""

from sylvan.database.orm import (
    FileImport,
    FileRecord,
    Quality,
    Reference,
    Repo,
    Section,
    Symbol,
)
from sylvan.database.orm.models.usage_stats import UsageStats
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def remove_repo(repo: str) -> dict:
    """Delete an indexed repository and all associated data.

    Removes usage_stats, workspace_repos, references, quality, imports,
    sections, symbols, files, and the repo record in FK-safe order
    using ORM subquery chains inside a transaction.

    Args:
        repo: The repository name to remove.

    Returns:
        Tool response dict with per-table deletion counts and ``_meta`` envelope.

    Raises:
        RepoNotFoundError: If no repository with the given name exists.
    """
    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

    repo_id = repo_obj.id
    files_q = FileRecord.where(repo_id=repo_id).to_subquery("id")
    symbols_q = Symbol.query().where_in_subquery("file_id", files_q).to_subquery("symbol_id")
    counts: dict[str, int] = {}

    from sylvan.database.orm.runtime.connection_manager import get_backend
    backend = get_backend()

    async with backend.transaction():
        counts["usage_stats"] = await UsageStats.where(repo_id=repo_id).delete()

        await backend.execute(
            "DELETE FROM workspace_repos WHERE repo_id = ?", [repo_id],
        )

        counts["references"] = await Reference.query().where_in_subquery(
            "source_symbol_id", symbols_q,
        ).delete()

        counts["quality"] = await Quality.query().where_in_subquery(
            "symbol_id", symbols_q,
        ).delete()

        counts["file_imports"] = await FileImport.query().where_in_subquery(
            "file_id", files_q,
        ).delete()

        counts["sections"] = await Section.query().where_in_subquery(
            "file_id", files_q,
        ).delete()

        counts["symbols"] = await Symbol.query().where_in_subquery(
            "file_id", files_q,
        ).delete()

        counts["files"] = await FileRecord.where(repo_id=repo_id).delete()
        await repo_obj.delete()
        counts["repos"] = 1

    meta.set("repo", repo)
    meta.set("repo_id", repo_id)
    meta.set("total_deleted", sum(counts.values()))
    return wrap_response({"deleted": counts}, meta.build())
