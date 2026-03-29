"""MCP tool: get_symbol -- retrieve full source of a symbol."""

from sylvan.error_codes import SylvanError
from sylvan.services.symbol import SymbolService
from sylvan.tools.support.response import (
    check_staleness,
    ensure_orm,
    get_meta,
    log_tool_call,
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
    meta = get_meta()
    ensure_orm()

    svc = SymbolService().with_source().with_file()
    if verify:
        svc = svc.verified()
    if context_lines > 0:
        svc = svc.with_context_lines(context_lines)

    try:
        sym = await svc.find(symbol_id, repo=repo)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    result = await sym._model.to_detail_dict()
    if sym.context_lines and sym.context_lines > 0:
        result["source"] = sym.source
        result["context_lines"] = sym.context_lines

    if sym.hash_verified is not None:
        result["hash_verified"] = sym.hash_verified
        if sym.drift_warning:
            result["drift_warning"] = sym.drift_warning

    if sym.source and sym.file_record:
        from sylvan.tools.support.token_counting import count_tokens

        file_content = await sym.file_record.get_content()
        returned = count_tokens(sym.source)
        if returned is not None and file_content:
            file_text = file_content.decode("utf-8", errors="replace")
            equivalent = count_tokens(file_text)
            if equivalent and returned > 0 and equivalent > 0:
                meta.record_token_efficiency(returned, equivalent)

    response = wrap_response(result, meta.build(), include_hints=True)

    if sym.file_record:
        await check_staleness(sym.file_record.repo_id, response)

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
    meta = get_meta()
    ensure_orm()

    svc = SymbolService().with_source().with_file()
    found_results = await svc.find_many(symbol_ids)

    found_ids = {r.symbol_id for r in found_results}
    not_found = [sid for sid in symbol_ids if sid not in found_ids]
    repo_ids: set[int] = set()

    symbols = []
    for r in found_results:
        if r.file_record:
            repo_ids.add(r.file_record.repo_id)
        file_path = await r._model._resolve_file_path()
        symbols.append(
            {
                "symbol_id": r.symbol_id,
                "name": r.name,
                "kind": r.kind,
                "language": r.language,
                "file": file_path,
                "signature": r.signature or "",
                "source": r.source or "",
            }
        )

    data = {"symbols": symbols, "not_found": not_found}

    meta.set("found", len(symbols))
    meta.set("not_found", len(not_found))

    response = wrap_response(data, meta.build())
    for rid in repo_ids:
        await check_staleness(rid, response)
    return response
