"""Drift test for the hand-maintained filter constants.

When :mod:`sylvan.security.patterns` and
``rust/crates/sylvan-security/src/filters.rs`` drift apart, indexing on
the Python and Rust sides would diverge. This test parses both sources
and asserts every constant set is byte-identical.
"""

from __future__ import annotations

import re
from pathlib import Path

from sylvan.security import patterns

_FILTERS_RS = Path(__file__).resolve().parent.parent / "rust" / "crates" / "sylvan-security" / "src" / "filters.rs"


def _rust_const_values(source: str, name: str) -> set[str]:
    match = re.search(
        rf"pub const {re.escape(name)}: &\[&str\] = &\[(.*?)\];",
        source,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"{name} not found in filters.rs")
    return set(re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1)))


def _assert_in_sync(const_name: str, python_set: set[str]) -> None:
    rust_source = _FILTERS_RS.read_text(encoding="utf-8")
    rust_set = _rust_const_values(rust_source, const_name)
    missing_on_rust = python_set - rust_set
    missing_on_python = rust_set - python_set
    assert not missing_on_rust and not missing_on_python, (
        f"{const_name} drift:\n"
        f"  only in Python ({len(missing_on_rust)}): {sorted(missing_on_rust)}\n"
        f"  only in Rust ({len(missing_on_python)}): {sorted(missing_on_python)}"
    )


def test_skip_dirs_in_sync() -> None:
    _assert_in_sync("SKIP_DIRS", set(patterns.SKIP_DIRS))


def test_skip_file_patterns_in_sync() -> None:
    _assert_in_sync("SKIP_FILE_PATTERNS", set(patterns.SKIP_FILE_PATTERNS))


def test_secret_patterns_in_sync() -> None:
    _assert_in_sync("SECRET_PATTERNS", set(patterns.SECRET_PATTERNS))


def test_binary_extensions_in_sync() -> None:
    _assert_in_sync("BINARY_EXTENSIONS", set(patterns.BINARY_EXTENSIONS))


def test_doc_extensions_in_sync() -> None:
    _assert_in_sync("DOC_EXTENSIONS", set(patterns.DOC_EXTENSIONS))
