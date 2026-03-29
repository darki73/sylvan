"""MCP tool: get_file_outline -- hierarchical symbol outline for a file."""

import json

from sylvan.error_codes import SylvanError
from sylvan.services.symbol import SymbolService
from sylvan.tools.support.response import (
    check_staleness,
    ensure_orm,
    get_meta,
    log_tool_call,
    wrap_response,
)
from sylvan.tools.support.token_counting import count_tokens


@log_tool_call
async def get_file_outline(repo: str, file_path: str) -> dict:
    """Get a hierarchical symbol outline for a specific file.

    Args:
        repo: Repository name.
        file_path: Relative file path within the repo.

    Returns:
        Tool response dict with ``outline`` tree and ``_meta`` envelope.

    Raises:
        RepoNotFoundError: If the repository name is not indexed.
        IndexFileNotFoundError: If the file path does not exist in the repo's index.
    """
    meta = get_meta()
    ensure_orm()

    try:
        data = await SymbolService().file_outline(repo, file_path)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    repo_id = data.pop("repo_id")
    file_rec = data.pop("file_rec")
    symbol_count = data.pop("symbol_count")

    meta.set("symbol_count", symbol_count)

    returned_text = json.dumps(data["outline"], default=str)
    token_count = count_tokens(returned_text)
    returned_tokens = token_count if token_count is not None else max(1, len(returned_text) // 4)
    if file_rec.byte_size:
        equivalent_tokens = file_rec.byte_size // 4
        if returned_tokens > 0 and equivalent_tokens > 0:
            method = "tiktoken_cl100k" if token_count is not None else "byte_estimate"
            meta.record_token_efficiency(returned_tokens, equivalent_tokens, method=method)

    response = wrap_response(data, meta.build())
    await check_staleness(repo_id, response)
    return response


@log_tool_call
async def get_file_outlines(repo: str, file_paths: list[str]) -> dict:
    """Batch retrieve outlines for multiple files in one call.

    Args:
        repo: Repository name.
        file_paths: List of relative file paths within the repo.

    Returns:
        Tool response dict with ``outlines`` list, ``not_found`` list,
        and ``_meta`` envelope.

    Raises:
        RepoNotFoundError: If the repository name is not indexed.
    """
    meta = get_meta()
    ensure_orm()

    try:
        data = await SymbolService().file_outlines(repo, file_paths)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    repo_id = data.pop("repo_id")

    returned_tokens = 0
    equivalent_tokens = 0
    used_tiktoken = False

    cleaned_outlines = []
    for outline_entry in data["outlines"]:
        file_rec = outline_entry.pop("file_rec")
        outline_text = json.dumps(outline_entry["outline"], default=str)
        token_count = count_tokens(outline_text)
        if token_count is not None:
            used_tiktoken = True
        returned_tokens += token_count if token_count is not None else max(1, len(outline_text) // 4)
        if file_rec.byte_size:
            equivalent_tokens += file_rec.byte_size // 4
        cleaned_outlines.append(outline_entry)

    if returned_tokens > 0 and equivalent_tokens > 0:
        method = "tiktoken_cl100k" if used_tiktoken else "byte_estimate"
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method=method)

    meta.set("found", len(cleaned_outlines))
    meta.set("not_found", len(data["not_found"]))
    response = wrap_response({"outlines": cleaned_outlines, "not_found": data["not_found"]}, meta.build())
    await check_staleness(repo_id, response)
    return response
