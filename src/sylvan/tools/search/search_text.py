"""MCP tool: search_text -- full-text search across file content."""

import json

from sylvan.context import get_context
from sylvan.database.orm import FileRecord
from sylvan.database.orm.models.blob import Blob
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response
from sylvan.tools.support.token_counting import count_tokens


async def _search_file_content(
    file_record: object,
    query_lower: str,
    context_lines: int,
    repo_name: str,
) -> list[dict]:
    """Search a single file's content for case-insensitive text matches.

    Args:
        file_record: The ORM file record to search.
        query_lower: The lowercased search query.
        context_lines: Number of surrounding lines to include per match.
        repo_name: Display name of the repository.

    Returns:
        List of match dicts with file path, line number, and context.
    """
    content = await Blob.get(file_record.content_hash)
    if content is None:
        return []

    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        return []

    matches = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if query_lower in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            context = "\n".join(lines[start:end])

            matches.append({
                "file_path": file_record.path,
                "repo_name": repo_name,
                "line": i + 1,
                "match": line.strip(),
                "context": context,
            })

    return matches


@log_tool_call
async def search_text(
    query: str,
    repo: str | None = None,
    file_pattern: str | None = None,
    max_results: int = 20,
    context_lines: int = 2,
) -> dict:
    """Search across file content for text matches (like grep).

    Searches cached blob content without hitting the filesystem.

    Args:
        query: Text to search for (case-insensitive).
        repo: Repository name filter.
        file_pattern: Glob pattern to filter by file path.
        max_results: Maximum matches to return.
        context_lines: Number of surrounding lines per match.

    Returns:
        Tool response dict with ``matches`` list and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    max_results = clamp(max_results, 1, 1000)
    context_lines = clamp(context_lines, 0, 50)
    ensure_orm()

    ctx = get_context()
    ctx.session.record_query(query, "search_text")

    query_builder = FileRecord.query().join("repos", "repos.id = files.repo_id")

    if repo:
        query_builder = query_builder.where("repos.name", repo)
    if file_pattern:
        query_builder = query_builder.where_glob("files.path", file_pattern)

    query_builder = query_builder.order_by("files.path")
    files = await query_builder.get()

    results = []
    query_lower = query.lower()

    for file_record in files:
        await file_record.load("repo")
        repo_obj = file_record.repo
        repo_name = repo_obj.name if repo_obj else ""

        matches = await _search_file_content(file_record, query_lower, context_lines, repo_name)
        for match in matches:
            results.append(match)
            if len(results) >= max_results:
                break

        if len(results) >= max_results:
            break

    meta.set("results_count", len(results))
    meta.set("query", query)

    # Token efficiency: returned tokens vs equivalent full-file reads
    returned_text = json.dumps(results, default=str)
    token_count = count_tokens(returned_text)
    returned_tokens = token_count if token_count is not None else max(1, len(returned_text) // 4)
    unique_files: dict[str, int] = {}
    for file_record in files:
        if file_record.path not in unique_files and file_record.byte_size:
            unique_files[file_record.path] = file_record.byte_size // 4
        if len(unique_files) >= len(results):
            break
    equivalent_tokens = sum(unique_files.values())
    if returned_tokens > 0 and equivalent_tokens > 0:
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method="byte_estimate")

    return wrap_response({"matches": results}, meta.build())
