"""MCP tool: get_symbol -- retrieve full source of a symbol."""

from sylvan.context import get_context
from sylvan.database.orm import Symbol
from sylvan.error_codes import SourceNotAvailableError, SymbolNotFoundError
from sylvan.indexing.source_code.extractor import compute_content_hash
from sylvan.tools.support.response import (
    MetaBuilder,
    check_staleness,
    ensure_orm,
    log_tool_call,
    record_savings,
    wrap_response,
)


@log_tool_call
async def get_symbol(
    symbol_id: str,
    repo: str | None = None,
    verify: bool = False,
    context_lines: int = 0,
) -> dict:
    """Retrieve the full source code of a symbol by its ID.

    Args:
        symbol_id: The stable symbol identifier (e.g., 'path::ClassName.method#method').
        verify: Re-hash content and warn if it has drifted since indexing.
        context_lines: Number of surrounding lines to include (0-50).

    Returns:
        Tool response dict with symbol source and ``_meta`` envelope.

    Raises:
        SymbolNotFoundError: If no symbol with the given ID exists.
        SourceNotAvailableError: If the symbol exists but its source blob is missing.
    """
    meta = MetaBuilder()
    ensure_orm()

    ctx = get_context()
    cache = ctx.cache
    cache_key = f"Symbol:{symbol_id}:{repo or ''}"
    found, symbol = cache.get(cache_key)
    if not found:
        query = Symbol.where(symbol_id=symbol_id).with_("file")
        if repo:
            query = query.join("files", "files.id = symbols.file_id").join(
                "repos", "repos.id = files.repo_id"
            ).where("repos.name", repo)
        symbol = await query.first()
        if symbol is not None:
            cache.put(cache_key, symbol)
    if symbol is None:
        raise SymbolNotFoundError(symbol_id=symbol_id, _meta=meta.build())

    source = await symbol.get_source()
    if not source:
        raise SourceNotAvailableError(symbol_id=symbol_id, _meta=meta.build())

    file_rec = symbol.file
    session = ctx.session
    session.record_symbol_access(symbol_id, await symbol._resolve_file_path())

    result = await symbol.to_detail_dict()

    if verify and symbol.content_hash:
        actual_hash = compute_content_hash(source.encode("utf-8"))
        result["hash_verified"] = actual_hash == symbol.content_hash
        if not result["hash_verified"]:
            result["drift_warning"] = "Content has changed since last indexing"

    await record_savings(meta, source, file_rec, session, symbols_retrieved=1)

    response = wrap_response(result, meta.build(), include_hints=True)

    if file_rec:
        await check_staleness(file_rec.repo_id, response)

    return response


@log_tool_call
async def get_symbols(symbol_ids: list[str]) -> dict:
    """Batch retrieve multiple symbols by ID.

    Args:
        symbol_ids: List of symbol identifiers.

    Returns:
        Tool response dict with ``symbols`` list, ``not_found`` list,
        and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    ctx = get_context()
    cache = ctx.cache
    results = []
    not_found = []

    for sid in symbol_ids:
        cache_key = f"Symbol:{sid}"
        found, symbol = cache.get(cache_key)
        if not found:
            symbol = await Symbol.where(symbol_id=sid).with_("file").first()
            if symbol is not None:
                cache.put(cache_key, symbol)
        if symbol is None:
            not_found.append(sid)
            continue

        source = await symbol.get_source()
        entry = {
            "symbol_id": symbol.symbol_id,
            "name": symbol.name,
            "kind": symbol.kind,
            "language": symbol.language,
            "file": await symbol._resolve_file_path(),
            "signature": symbol.signature or "",
            "source": source or "",
        }
        results.append(entry)

    meta.set("found", len(results))
    meta.set("not_found", len(not_found))

    return wrap_response(
        {"symbols": results, "not_found": not_found},
        meta.build(),
    )
