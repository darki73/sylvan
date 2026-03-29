"""MCP tool: remove_repo -- delete an indexed repository and all its data."""

from sylvan.tools.support.response import ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


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
    meta = get_meta()
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.repository import RepositoryService

        result = await RepositoryService().remove(repo)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    meta.set("repo", result["repo"])
    meta.set("repo_id", result["repo_id"])
    return wrap_response({"status": "removed", "repo": result["repo"]}, meta.build())
