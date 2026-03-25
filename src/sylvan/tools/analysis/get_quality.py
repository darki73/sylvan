"""MCP tool: get_quality -- quality metrics for symbols."""

from sylvan.database.orm import Quality, Repo
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def get_quality(
    repo: str,
    untested_only: bool = False,
    undocumented_only: bool = False,
    min_complexity: int = 0,
    limit: int = 50,
) -> dict:
    """Get quality metrics for symbols. Find untested, undocumented, or complex code.

    Lazily computes quality metrics on first access, then caches them.

    Args:
        repo: Repository name.
        untested_only: Only show untested symbols.
        undocumented_only: Only show undocumented symbols.
        min_complexity: Minimum cyclomatic complexity threshold.
        limit: Maximum results to return.

    Returns:
        Tool response dict with ``symbols`` quality list and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

    count = await (
        Quality.query()
        .join("symbols s", "s.symbol_id = quality.symbol_id")
        .join("files f", "f.id = s.file_id")
        .where("f.repo_id", repo_obj.id)
        .count()
    )

    if count == 0:
        from sylvan.analysis.quality.quality_metrics import compute_quality_metrics

        await compute_quality_metrics(repo_obj.id)

    from sylvan.analysis.quality.quality_metrics import get_low_quality_symbols

    results = await get_low_quality_symbols(
        repo,
        min_complexity=min_complexity,
        untested_only=untested_only,
        undocumented_only=undocumented_only,
        limit=limit,
    )

    meta.set("count", len(results))
    return wrap_response({"symbols": results}, meta.build())
