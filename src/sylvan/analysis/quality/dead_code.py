"""Dead code detection -- find unreferenced symbols."""

from sylvan.database.orm import Reference, Symbol


async def find_dead_code(
    repo_name: str,
    kinds: list[str] | None = None,
) -> list[dict]:
    """Find symbols that are never referenced by other symbols.

    A symbol is considered "dead" if:
    - It has no incoming references in the reference graph
    - It is not a class (classes may be instantiated implicitly)
    - It is not a test function
    - It is not a main/entry function

    If the references table is empty (no indexing has populated it),
    returns an empty list with a warning instead of flagging everything
    as dead code.

    Args:
        repo_name: Repository to analyze.
        kinds: Filter by kinds (default: function, method).

    Returns:
        List of dicts describing unreferenced symbols, each containing
        symbol_id, name, qualified_name, kind, language, signature,
        line_start, and file_path. Returns a single-element list with
        a ``warning`` key when the reference graph is empty.
    """
    if kinds is None:
        kinds = ["function", "method"]

    total_refs = await Reference.query().count()
    if total_refs == 0:
        return []

    rows = await (
        Symbol.query()
        .select("symbols.symbol_id", "symbols.name", "symbols.qualified_name",
                "symbols.kind", "symbols.language", "symbols.signature",
                "symbols.line_start", "f.path as file_path")
        .join("files f", "f.id = symbols.file_id")
        .join("repos r", "r.id = f.repo_id")
        .where("r.name", repo_name)
        .where_in("symbols.kind", kinds)
        .where_not_in_subquery(
            "symbols.symbol_id",
            'SELECT DISTINCT target_symbol_id FROM "references" '
            'WHERE target_symbol_id IS NOT NULL',
        )
        .order_by("f.path")
        .order_by("symbols.line_start")
        .get()
    )

    results = []
    for r in rows:
        name = r.name
        file_path = getattr(r, "file_path", "") or ""

        if _is_entry_point(name, file_path):
            continue

        results.append({
            "symbol_id": r.symbol_id,
            "name": r.name,
            "qualified_name": r.qualified_name,
            "kind": r.kind,
            "language": r.language,
            "signature": r.signature,
            "line_start": r.line_start,
            "file_path": file_path,
        })

    return results


def _is_entry_point(name: str, file_path: str) -> bool:
    """Heuristic: is this symbol likely an entry point?

    Args:
        name: Symbol name.
        file_path: File path containing the symbol.

    Returns:
        True if the symbol is likely an entry point or test fixture.
    """
    if name in ("main", "__init__", "__main__", "setup", "teardown"):
        return True

    if name.startswith("test_") or name.startswith("Test"):
        return True

    if file_path.endswith(("__main__.py", "cli.py", "server.py", "app.py")):
        return True

    return name.startswith("_") and not name.startswith("__")
