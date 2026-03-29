"""MCP tool: get_context_bundle -- symbol + imports + callers in one call."""

import json

from sylvan.context import get_context
from sylvan.database.orm import FileImport, FileRecord, Symbol
from sylvan.error_codes import SymbolNotFoundError
from sylvan.tools.support.response import (
    check_staleness,
    ensure_orm,
    get_meta,
    log_tool_call,
    wrap_response,
)
from sylvan.tools.support.token_counting import count_tokens


@log_tool_call
async def get_context_bundle(
    symbol_id: str,
    include_callers: bool = False,
    include_imports: bool = True,
) -> dict:
    """Get a context bundle for a symbol: source + imports + optionally callers.

    This is the most efficient way to understand a symbol in context --
    one call instead of multiple get_symbol + search queries.

    Args:
        symbol_id: Symbol to get context for.
        include_callers: Include files that reference this symbol.
        include_imports: Include import statements from the symbol's file.

    Returns:
        Tool response dict with symbol source, imports, siblings, and
        optionally callers, plus ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    ctx = get_context()
    session = ctx.session

    symbol = await Symbol.where(symbol_id=symbol_id).with_("file").first()
    if symbol is None:
        raise SymbolNotFoundError(symbol_id=symbol_id, _meta=meta.build())

    source = await symbol.get_source()
    file_rec = symbol.file
    file_path = file_rec.path if file_rec else ""
    session.record_symbol_access(symbol_id, file_path)

    bundle: dict = {
        "symbol": {
            "symbol_id": symbol.symbol_id,
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "kind": symbol.kind,
            "language": symbol.language,
            "file": file_path,
            "signature": symbol.signature or "",
            "docstring": symbol.docstring or "",
            "decorators": symbol.decorators or [],
            "source": source or "",
        },
    }

    if include_imports:
        imports = await FileImport.where(file_id=symbol.file_id).get()
        bundle["imports"] = [
            {
                "specifier": imp.specifier,
                "names": imp.names or [],
            }
            for imp in imports
        ]

    if include_callers:
        caller_files = await (
            FileRecord.query()
            .select("DISTINCT files.path", "files.language")
            .join("file_imports fi", "fi.file_id = files.id")
            .where("fi.resolved_file_id", symbol.file_id)
            .limit(20)
            .get()
        )
        bundle["callers"] = [{"path": c.path, "language": c.language} for c in caller_files]

    siblings = await (
        Symbol.where(file_id=symbol.file_id).where_not(symbol_id=symbol_id).order_by("line_start").limit(10).get()
    )
    bundle["siblings"] = [
        {
            "symbol_id": sibling.symbol_id,
            "name": sibling.name,
            "kind": sibling.kind,
            "signature": sibling.signature or "",
            "line_start": sibling.line_start,
        }
        for sibling in siblings
    ]

    meta.set("has_imports", bool(bundle.get("imports")))
    meta.set("has_callers", bool(bundle.get("callers")))
    meta.set("siblings_count", len(bundle["siblings"]))

    returned_text = json.dumps(bundle, default=str)
    token_count = count_tokens(returned_text)
    returned_tokens = token_count if token_count is not None else max(1, len(returned_text) // 4)
    if file_rec and file_rec.byte_size:
        equivalent_tokens = file_rec.byte_size // 4
        if returned_tokens > 0 and equivalent_tokens > 0:
            method = "tiktoken_cl100k" if token_count is not None else "byte_estimate"
            meta.record_token_efficiency(returned_tokens, equivalent_tokens, method=method)

    response = wrap_response(bundle, meta.build(), include_hints=True)
    if file_rec:
        await check_staleness(file_rec.repo_id, response)
    return response
