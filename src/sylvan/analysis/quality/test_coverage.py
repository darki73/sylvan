"""Test coverage analysis — import + call based detection."""

from __future__ import annotations

import re

from sylvan.database.orm import FileImport, FileRecord, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.logging import get_logger

logger = get_logger(__name__)

# Matches function/constructor/method calls: name(
_CALL_PATTERN = re.compile(r"\b([a-zA-Z_]\w+)\s*\(")


async def analyze_test_coverage(repo_id: int) -> dict:
    """Analyze which symbols have tests that import and call them.

    Uses static analysis of test file imports and function call patterns
    to determine coverage without executing tests.

    Strategy:
        1. Find all test files (path contains 'test' or 'spec').
        2. For each test file, collect its imports from the ``file_imports`` table.
        3. Read test file blobs and extract every called name via regex.
        4. A symbol is "covered" when *both* conditions are met:
           - Its module (or any parent) appears in imported specifiers, AND
           - Its name appears as a call site in a test file.

    Args:
        repo_id: Database ID of the repository.

    Returns:
        Dict with ``covered`` (list of symbol_ids), ``uncovered`` (list),
        and ``coverage_percent`` (float 0-100).
    """
    # Get all non-test symbols (functions, methods, classes)
    all_symbols = await (
        Symbol.query()
        .select(
            "symbols.symbol_id",
            "symbols.name",
            "symbols.file_id",
            "symbols.kind",
        )
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo_id)
        .where_not_like("files.path", "%test%")
        .where_not_like("files.path", "%spec%")
        .where_in("symbols.kind", ["function", "method", "class"])
        .get()
    )

    test_files = await (
        FileRecord.where(repo_id=repo_id)
        .where_group(lambda q: q.where_like("path", "%test%").or_where_like("path", "%spec%"))
        .get()
    )

    if not test_files or not all_symbols:
        return {
            "covered": [],
            "uncovered": [s.symbol_id for s in all_symbols],
            "coverage_percent": 0.0,
        }

    # Collect imported specifiers and explicitly imported names from test files
    test_file_ids = [f.id for f in test_files]
    imported_specifiers: set[str] = set()

    for fid in test_file_ids:
        imports = await FileImport.where(file_id=fid).get()
        for imp in imports:
            imported_specifiers.add(imp.specifier)
            if isinstance(imp.names, list):
                for name in imp.names:
                    imported_specifiers.add(name)

    # Read test file blobs and extract every function/method call site
    called_names: set[str] = set()
    for tf in test_files:
        content = await Blob.get(tf.content_hash)
        if content:
            text = content.decode("utf-8", errors="replace")
            for match in _CALL_PATTERN.finditer(text):
                called_names.add(match.group(1))

    # Build path -> module mapping for source files
    source_files = await FileRecord.where(repo_id=repo_id).get()
    file_id_to_module: dict[int, str] = {}
    for f in source_files:
        if not f.path:
            continue
        module = f.path.replace("/", ".").replace("\\", ".")
        if module.endswith(".py"):
            module = module[:-3]
        file_id_to_module[f.id] = module

    # Cross-reference: covered = name called AND module imported
    covered: list[str] = []
    uncovered: list[str] = []

    for sym in all_symbols:
        module = file_id_to_module.get(sym.file_id, "")
        name_called = sym.name in called_names
        module_imported = any(
            spec in module or module in spec for spec in imported_specifiers
        )

        if name_called and module_imported:
            covered.append(sym.symbol_id)
        else:
            uncovered.append(sym.symbol_id)

    total = len(all_symbols)
    pct = round(len(covered) / total * 100, 1) if total > 0 else 0.0

    return {
        "covered": covered,
        "uncovered": uncovered,
        "coverage_percent": pct,
    }
