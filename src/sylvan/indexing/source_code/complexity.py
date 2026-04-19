"""Per-symbol complexity metrics.

Backed by ``sylvan-indexing`` (Rust) since v2.x. Public signature is
unchanged: ``compute_complexity(source, language) -> dict``.
"""

from __future__ import annotations

from sylvan._rust import compute_complexity as _rust_compute_complexity


def compute_complexity(source: str, language: str) -> dict[str, int]:
    """Compute complexity metrics for a symbol's source body.

    Args:
        source: Raw source text of the symbol.
        language: Canonical language identifier (``"python"``,
            ``"javascript"``, ``"rust"``, ...). Unknown identifiers fall
            back to a generic decision pattern.

    Returns:
        Dict with ``cyclomatic``, ``max_nesting``, and ``param_count`` keys.
    """
    return _rust_compute_complexity(source, language)
