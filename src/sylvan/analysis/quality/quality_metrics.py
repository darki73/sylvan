"""Quality scoring -- has tests? docs? types? complexity?"""

import re

from sylvan.database.orm import FileRecord, Quality, Symbol
from sylvan.database.orm.runtime.connection_manager import get_backend


async def compute_quality_metrics(
    repo_id: int,
) -> int:
    """Compute quality metrics for all symbols in a repo.

    Populates the quality table with:
    - has_tests: whether a test file references this symbol
    - has_docs: whether a docstring exists
    - has_types: whether type annotations are present in signature
    - complexity: rough cyclomatic complexity estimate

    Args:
        repo_id: Database ID of the repository.

    Returns:
        Number of symbols scored.
    """
    from sylvan.database.orm.models.blob import Blob

    backend = get_backend()

    symbols = await (
        Symbol.query()
        .select(
            "symbols.symbol_id",
            "symbols.name",
            "symbols.kind",
            "symbols.signature",
            "symbols.docstring",
            "symbols.byte_offset",
            "symbols.byte_length",
            "symbols.cyclomatic",
            "f.content_hash",
            "f.path",
        )
        .join("files f", "f.id = symbols.file_id")
        .where("f.repo_id", repo_id)
        .get()
    )

    test_files = await (
        FileRecord.where(repo_id=repo_id)
        .where_group(lambda q: q.where_like("path", "%test%").or_where_like("path", "%spec%"))
        .select("id", "content_hash")
        .get()
    )

    tested_names: set[str] = set()
    for tf in test_files:
        content = await Blob.get(tf.content_hash)
        if content:
            text = content.decode("utf-8", errors="replace")
            for match in re.finditer(r"\b([a-zA-Z_]\w{2,})\b", text):
                tested_names.add(match.group(1))

    scored = 0
    for sym in symbols:
        name = sym.name
        sig = sym.signature or ""
        docstring = sym.docstring or ""

        has_tests = name in tested_names
        has_docs = len(docstring.strip()) > 10
        has_types = _has_type_annotations(sig)

        stored_cyclomatic = getattr(sym, "cyclomatic", 0) or 0
        if stored_cyclomatic > 0:
            complexity = stored_cyclomatic
        else:
            complexity = 0
            content_hash = getattr(sym, "content_hash", None)
            if content_hash:
                content = await Blob.get(content_hash)
                if content:
                    source = content[sym.byte_offset : sym.byte_offset + sym.byte_length]
                    source_text = source.decode("utf-8", errors="replace")
                    complexity = _estimate_complexity(source_text)

        await Quality.insert_or_replace(
            symbol_id=sym.symbol_id,
            has_tests=has_tests,
            has_docs=has_docs,
            has_types=has_types,
            complexity=complexity,
        )
        scored += 1

    await backend.commit()
    return scored


async def get_quality(symbol_id: str) -> dict | None:
    """Get quality metrics for a symbol.

    Args:
        symbol_id: Unique identifier of the symbol.

    Returns:
        Dictionary with quality metrics, or None if not scored.
    """
    q = await Quality.where(symbol_id=symbol_id).first()
    if q is None:
        return None
    return {
        "symbol_id": q.symbol_id,
        "has_tests": q.has_tests,
        "has_docs": q.has_docs,
        "has_types": q.has_types,
        "complexity": q.complexity,
        "change_frequency": q.change_frequency,
        "last_changed": q.last_changed,
    }


async def get_low_quality_symbols(
    repo_name: str,
    min_complexity: int = 5,
    untested_only: bool = False,
    undocumented_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Find symbols with quality concerns.

    Args:
        repo_name: Repository to analyze.
        min_complexity: Minimum complexity threshold to flag.
        untested_only: If True, only return untested symbols.
        undocumented_only: If True, only return undocumented symbols.
        limit: Maximum number of results to return.

    Returns:
        List of dicts with quality metrics and symbol metadata.
    """
    query = (
        Quality.query()
        .select(
            "quality.*",
            "s.name",
            "s.qualified_name",
            "s.kind",
            "s.language",
            "s.signature",
            "s.cyclomatic as sym_cyclomatic",
            "s.max_nesting",
            "s.param_count",
            "f.path as file_path",
        )
        .join("symbols s", "s.symbol_id = quality.symbol_id")
        .join("files f", "f.id = s.file_id")
        .join("repos r", "r.id = f.repo_id")
        .where("r.name", repo_name)
    )

    def _quality_filters(q: object) -> None:
        if untested_only:
            q.or_where("quality.has_tests", 0)
        if undocumented_only:
            q.or_where("quality.has_docs", 0)
        if min_complexity > 0:
            q.or_where_raw(f"quality.complexity >= {min_complexity}")

    if untested_only or undocumented_only or min_complexity > 0:
        query = query.where_group(_quality_filters)

    results = await query.order_by("quality.complexity", "DESC").limit(limit).get()

    return [
        {
            "symbol_id": r.symbol_id,
            "has_tests": r.has_tests,
            "has_docs": r.has_docs,
            "has_types": r.has_types,
            "complexity": r.complexity,
            "cyclomatic": getattr(r, "sym_cyclomatic", None) or r.complexity,
            "max_nesting": getattr(r, "max_nesting", 0) or 0,
            "param_count": getattr(r, "param_count", 0) or 0,
            "change_frequency": r.change_frequency,
            "last_changed": r.last_changed,
            "name": getattr(r, "name", None),
            "qualified_name": getattr(r, "qualified_name", None),
            "kind": getattr(r, "kind", None),
            "language": getattr(r, "language", None),
            "signature": getattr(r, "signature", None),
            "file_path": getattr(r, "file_path", None),
        }
        for r in results
    ]


def _has_type_annotations(signature: str) -> bool:
    """Check if a signature contains type annotations.

    Args:
        signature: Symbol signature string.

    Returns:
        True if type annotations are detected.
    """
    if "->" in signature or ": " in signature:
        return True
    return bool(re.search(r":\s*\w+", signature))


# Keywords that increase cyclomatic complexity
_BRANCH_KEYWORDS = re.compile(r"\b(if|elif|else|for|while|except|catch|case|switch|and|or|&&|\|\|)\b")


def _estimate_complexity(source: str) -> int:
    """Rough cyclomatic complexity: 1 + count of branching keywords.

    Args:
        source: Source code text of the symbol.

    Returns:
        Estimated cyclomatic complexity score.
    """
    return 1 + len(_BRANCH_KEYWORDS.findall(source))
