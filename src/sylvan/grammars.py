"""Tree-sitter grammar cache configuration.

Points the Rust extraction layer at ``<sylvan_home>/tree-sitter-grammars/``
so downloaded grammars stay colocated with the rest of sylvan's state and
survive a wipe of the user's platform cache directory. Grammar loading is
owned entirely by Rust; this module only tells it where to cache.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

_configured = False
_lock = Lock()


def _sylvan_home() -> Path:
    return Path(os.environ.get("SYLVAN_HOME", Path.home() / ".sylvan"))


def grammar_cache_dir() -> Path:
    """Return the grammar cache directory, creating it if needed."""
    path = _sylvan_home() / "tree-sitter-grammars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def configure() -> None:
    """Point the Rust grammar loader at the sylvan-home cache.

    Idempotent: only the first call does any work.
    """
    global _configured
    with _lock:
        if _configured:
            return

        from sylvan._rust import configure_grammar_cache

        configure_grammar_cache(str(grammar_cache_dir()))
        _configured = True
