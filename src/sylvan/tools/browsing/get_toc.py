"""MCP tool: get_toc -- table of contents for indexed documentation."""

from sylvan.database.orm import Repo
from sylvan.services.section import SectionService
from sylvan.tools.support.response import (
    check_staleness,
    ensure_orm,
    get_meta,
    log_tool_call,
    wrap_response,
)


@log_tool_call
async def get_toc(
    repo: str,
    doc_path: str | None = None,
) -> dict:
    """Get a flat table of contents for indexed documentation.

    Args:
        repo: Repository name.
        doc_path: Optional filter to a specific document path.

    Returns:
        Tool response dict with ``toc`` list and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    data = await SectionService().toc(repo, doc_path=doc_path)
    data.pop("repo_name")

    meta.set("section_count", data.pop("section_count"))
    response = wrap_response(data, meta.build())
    repo_obj = await Repo.where(name=repo).first()
    if repo_obj:
        await check_staleness(repo_obj.id, response)
    return response


@log_tool_call
async def get_toc_tree(repo: str, max_depth: int = 3) -> dict:
    """Get a nested tree table of contents, grouped by document.

    Args:
        repo: Repository name.
        max_depth: Max heading depth to include (1--6, default 3).

    Returns:
        Tool response dict with ``tree`` list and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    data = await SectionService().toc_tree(repo, max_depth=max_depth)
    data.pop("repo_name")

    meta.set("document_count", data.pop("document_count"))
    meta.set("section_count", data.pop("section_count"))
    truncated = data.pop("truncated_sections", None)
    depth = data.pop("max_depth", None)
    if truncated:
        meta.set("truncated_sections", truncated)
        meta.set("max_depth", depth)

    response = wrap_response(data, meta.build())
    repo_obj = await Repo.where(name=repo).first()
    if repo_obj:
        await check_staleness(repo_obj.id, response)
    return response
