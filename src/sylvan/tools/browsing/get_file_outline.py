"""MCP tool: get_file_outline -- hierarchical symbol outline for a file."""

import json

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.error_codes import IndexFileNotFoundError, RepoNotFoundError
from sylvan.logging import get_logger
from sylvan.tools.support.response import MetaBuilder, check_staleness, ensure_orm, log_tool_call, wrap_response
from sylvan.tools.support.token_counting import count_tokens

logger = get_logger(__name__)


def _build_symbol_tree(items: list[dict]) -> list[dict]:
    """Organise flat symbol entries into a parent-child tree structure.

    Args:
        items: Flat list of symbol dicts, each with ``symbol_id`` and
            optional ``parent_symbol_id``.

    Returns:
        List of root-level symbol dicts, each with a ``children`` list.
    """
    root_symbols = []
    by_id: dict[str, dict] = {}
    for item in items:
        symbol_id = item["symbol_id"]
        if symbol_id in by_id:
            logger.debug("duplicate_symbol_id_in_outline", symbol_id=symbol_id)
        by_id[symbol_id] = {**item, "children": []}
    for item in items:
        node = by_id[item["symbol_id"]]
        parent_id = item.get("parent_symbol_id")
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            root_symbols.append(node)
    return root_symbols


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
    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

    file_rec = await (FileRecord.query()
                .where(repo_id=repo_obj.id)
                .where(path=file_path)
                .first())
    if file_rec is None:
        raise IndexFileNotFoundError(file_path=file_path, repo=repo, _meta=meta.build())

    symbols = await (Symbol.in_repo(repo)
               .in_file(file_path)
               .order_by("symbols.line_start")
               .get())

    items = [
        {
            "symbol_id": symbol.symbol_id,
            "name": symbol.name,
            "kind": symbol.kind,
            "signature": symbol.signature or "",
            "line_start": symbol.line_start,
            "line_end": symbol.line_end,
            "parent_symbol_id": symbol.parent_symbol_id,
        }
        for symbol in symbols
    ]

    root_symbols = _build_symbol_tree(items)

    meta.set("symbol_count", len(items))

    returned_text = json.dumps(root_symbols, default=str)
    token_count = count_tokens(returned_text)
    returned_tokens = token_count if token_count is not None else max(1, len(returned_text) // 4)
    if file_rec.byte_size:
        equivalent_tokens = file_rec.byte_size // 4
        if returned_tokens > 0 and equivalent_tokens > 0:
            method = "tiktoken_cl100k" if token_count is not None else "byte_estimate"
            meta.record_token_efficiency(returned_tokens, equivalent_tokens, method=method)

    response = wrap_response({"file": file_path, "outline": root_symbols}, meta.build())
    await check_staleness(repo_obj.id, response)
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
    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

    outlines = []
    not_found = []
    returned_tokens = 0
    equivalent_tokens = 0

    for fp in file_paths:
        file_rec = await (FileRecord.query()
                    .where(repo_id=repo_obj.id)
                    .where(path=fp)
                    .first())
        if file_rec is None:
            not_found.append(fp)
            continue

        symbols = await (Symbol.in_repo(repo)
                   .in_file(fp)
                   .order_by("symbols.line_start")
                   .get())

        items = [
            {
                "symbol_id": s.symbol_id,
                "name": s.name,
                "kind": s.kind,
                "signature": s.signature or "",
                "line_start": s.line_start,
                "line_end": s.line_end,
                "parent_symbol_id": s.parent_symbol_id,
            }
            for s in symbols
        ]

        tree = _build_symbol_tree(items)
        outline_text = json.dumps(tree, default=str)
        token_count = count_tokens(outline_text)
        returned_tokens += token_count if token_count is not None else max(1, len(outline_text) // 4)
        if file_rec.byte_size:
            equivalent_tokens += file_rec.byte_size // 4

        outlines.append({
            "file": fp,
            "outline": tree,
            "symbol_count": len(items),
        })

    if returned_tokens > 0 and equivalent_tokens > 0:
        meta.record_token_efficiency(returned_tokens, equivalent_tokens, method="byte_estimate")

    meta.set("found", len(outlines))
    meta.set("not_found", len(not_found))
    response = wrap_response({"outlines": outlines, "not_found": not_found}, meta.build())
    await check_staleness(repo_obj.id, response)
    return response
