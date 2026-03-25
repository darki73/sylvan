"""MCP tool: search_sections -- search indexed documentation sections."""

import json

from sylvan.context import get_context
from sylvan.database.orm import Repo, Section
from sylvan.error_codes import EmptyQueryError
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response
from sylvan.tools.support.token_counting import count_tokens


@log_tool_call
async def search_sections(
    query: str,
    repo: str | None = None,
    doc_path: str | None = None,
    max_results: int = 10,
) -> dict:
    """Search indexed documentation sections by title, summary, or tags.

    Args:
        query: Search query string.
        repo: Filter to a specific repository name.
        doc_path: Filter to a specific document path.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``sections`` list and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    max_results = clamp(max_results, 1, 1000)
    ensure_orm()

    ctx = get_context()
    ctx.session.record_query(query, "search_sections")

    if not query or not query.strip():
        raise EmptyQueryError(_meta=meta.build())

    query_builder = Section.search(query)

    if repo:
        query_builder = query_builder.in_repo(repo)
    if doc_path:
        query_builder = query_builder.in_doc(doc_path)

    query_builder = query_builder.limit(max_results)
    sections = await query_builder.get()

    formatted = []
    for section in sections:
        await section.load("file")
        file_rec = section.file
        if file_rec:
            await file_rec.load("repo")
        repo_obj = file_rec.repo if file_rec else None
        formatted.append(
            {
                "section_id": section.section_id,
                "title": section.title,
                "level": section.level,
                "summary": section.summary or "",
                "file": file_rec.path if file_rec else "",
                "repo": repo_obj.name if repo_obj else "",
            }
        )

    meta.set("results_count", len(formatted))
    meta.set("query", query)

    # Token efficiency: returned tokens vs equivalent full-file reads
    returned_text = json.dumps(formatted, default=str)
    token_count = count_tokens(returned_text)
    returned_tokens = token_count if token_count is not None else max(1, len(returned_text) // 4)
    unique_files: dict[str, int] = {}
    for section in sections:
        file_rec = section.file
        if file_rec and file_rec.path not in unique_files and file_rec.byte_size:
            unique_files[file_rec.path] = file_rec.byte_size // 4
    equivalent_tokens = sum(unique_files.values())
    if returned_tokens > 0 and equivalent_tokens > 0:
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method="byte_estimate")

    if repo:
        repo_obj = await Repo.where(name=repo).first()
        if repo_obj:
            meta.set("repo_id", repo_obj.id)

    return wrap_response({"sections": formatted}, meta.build())
