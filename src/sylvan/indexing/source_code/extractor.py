"""Symbol extraction entry point.

Thin Python wrapper over the Rust extraction layer. `parse_file` takes
source text, a filename, and a language identifier and returns a list
of [`Symbol`][sylvan.database.validation.Symbol] instances extracted
by the Rust pipeline. Languages outside the Rust registry return an
empty list - the Python-side fallback path retired when the Rust port
reached full language coverage.
"""

import hashlib

from sylvan._rust import (
    extract_symbols as _rust_extract_symbols,
)
from sylvan._rust import (
    supported_languages as _rust_supported_languages,
)
from sylvan.database.validation import Symbol
from sylvan.grammars import configure as _configure_grammars

_configure_grammars()

_RUST_LANGUAGES: frozenset[str] = frozenset(_rust_supported_languages())
"""Languages registered with the Rust extractor. Built once at import
time from the Rust registry so the Python and Rust views cannot drift."""


def compute_content_hash(source_bytes: bytes) -> str:
    """SHA-256 of the raw source bytes for drift detection.

    Args:
        source_bytes: Raw source code bytes.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(source_bytes).hexdigest()


def parse_file(content: str, filename: str, language: str) -> list[Symbol]:
    """Parse source code and extract symbols via the Rust extractor.

    Args:
        content: Source code text.
        filename: Relative file path.
        language: Language identifier (e.g. ``python``, ``typescript``).

    Returns:
        List of Symbol objects, or an empty list when `language` is
        not handled by the Rust extractor.
    """
    if language in _RUST_LANGUAGES:
        return [Symbol(**d) for d in _rust_extract_symbols(content, filename, language)]
    return []
