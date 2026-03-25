"""MCP tool: get_related -- find related symbols by co-location and naming."""

import re

from sylvan.database.orm import FileRecord, Symbol
from sylvan.error_codes import IndexFileNotFoundError, SymbolNotFoundError
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response

_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
"""Regex that splits camelCase and PascalCase boundaries for token extraction."""


def _tokenize_name(name: str) -> set[str]:
    """Split an identifier into lowercase tokens on camelCase, underscore, and separator boundaries.

    Args:
        name: The identifier string to tokenize.

    Returns:
        Set of lowercase token strings (minimum 2 characters each).
    """
    parts = _CAMEL_RE.sub("_", name)
    tokens = re.split(r"[_\-./]", parts)
    return {t.lower() for t in tokens if len(t) >= 2}


def _score_candidate(candidate: object, target_file_id: int, target_tokens: set[str]) -> float:
    """Compute a relatedness score for a candidate symbol.

    Args:
        candidate: An ORM symbol instance to score.
        target_file_id: The file ID of the target symbol.
        target_tokens: Lowercase name tokens of the target symbol.

    Returns:
        Numeric relatedness score (higher is more related).
    """
    score = 0.0

    if candidate.file_id == target_file_id:
        score += 3.0

    c_tokens = _tokenize_name(candidate.name)
    overlap = target_tokens & c_tokens
    score += 0.5 * len(overlap)

    return score


@log_tool_call
async def get_related(symbol_id: str, max_results: int = 10) -> dict:
    """Find symbols related to a given symbol.

    Scoring signals:
    - Same file: weight 3.0
    - Shared imports: weight 1.5
    - Name token overlap: weight 0.5

    Args:
        symbol_id: The symbol to find relations for.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``related`` list and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    max_results = clamp(max_results, 1, 100)
    ensure_orm()

    target = await Symbol.where(symbol_id=symbol_id).first()
    if target is None:
        raise SymbolNotFoundError(symbol_id=symbol_id, _meta=meta.build())

    target_tokens = _tokenize_name(target.name)
    target_file_id = target.file_id

    target_file = await FileRecord.find(target_file_id)
    if target_file is None:
        raise IndexFileNotFoundError(symbol_id=symbol_id, _meta=meta.build())

    candidates = await (
        Symbol.query()
        .select(
            "symbols.symbol_id",
            "symbols.name",
            "symbols.kind",
            "symbols.language",
            "symbols.signature",
            "symbols.file_id",
            "f.path as file_path",
        )
        .join("files f", "f.id = symbols.file_id")
        .where("f.repo_id", target_file.repo_id)
        .where_not(symbol_id=symbol_id)
        .limit(1000)
        .get()
    )

    scored = []
    for c in candidates:
        score = _score_candidate(c, target_file_id, target_tokens)
        if score > 0:
            scored.append(
                (
                    score,
                    {
                        "symbol_id": c.symbol_id,
                        "name": c.name,
                        "kind": c.kind,
                        "file_path": getattr(c, "file_path", ""),
                        "signature": c.signature or "",
                    },
                )
            )

    scored.sort(key=lambda x: -x[0])
    top = scored[:max_results]

    results = [
        {
            "symbol_id": sym["symbol_id"],
            "name": sym["name"],
            "kind": sym["kind"],
            "file": sym["file_path"],
            "signature": sym.get("signature", ""),
            "score": round(score, 2),
        }
        for score, sym in top
    ]

    meta.set("count", len(results))
    return wrap_response({"symbol_id": symbol_id, "related": results}, meta.build())
