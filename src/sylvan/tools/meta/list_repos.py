"""MCP tool: list_repos -- list all indexed repositories."""

from sylvan.tools.support.response import ensure_orm, get_meta, log_tool_call, wrap_response


@log_tool_call
async def list_repos() -> dict:
    """List all indexed repositories with summary statistics.

    Returns:
        Tool response dict with ``repos`` list and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    from sylvan.services.repository import RepositoryService

    repos = await RepositoryService().with_stats().get()
    meta.set("count", len(repos))
    return wrap_response(
        {
            "repos": [
                {
                    "id": r.id,
                    "name": r.name,
                    "source_path": r.source_path,
                    "github_url": r.github_url,
                    "indexed_at": r.indexed_at,
                    "git_head": r.git_head,
                    "file_count": r.stats["files"],
                    "symbol_count": r.stats["symbols"],
                }
                for r in repos
            ]
        },
        meta.build(),
    )
