"""Extract call sites from parsed source code.

Backed by ``sylvan-indexing`` (Rust) since v2.x. The tree-sitter walk
happens in Rust; Python is a thin hydration layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from sylvan._rust import extract_call_sites as _rust_extract_call_sites


@dataclass(slots=True)
class CallSite:
    """A function/method call found inside a symbol body.

    Attributes:
        caller_symbol_id: Symbol ID of the enclosing function/method.
        callee_name: Name being called (e.g., "foo", "self.bar", "Module.baz").
        line: 1-based line number of the call.
    """

    caller_symbol_id: str
    callee_name: str
    line: int


def extract_call_sites(
    symbols: list,
    content_str: str,
    language: str,
    repo_name: str,
) -> list[CallSite]:
    """Extract call sites from source code.

    For each function/method symbol in ``symbols`` the Rust backend
    walks the matching AST subtree and collects call expressions. Also
    captures module-level calls (outside any symbol body) under the
    literal ``"__module__"`` caller id.

    ``repo_name`` is currently not consumed by the backend. The original
    Python implementation computed ``f"{repo_name}::"`` as a prefix for
    module-level calls but the recipient function ignored the argument
    and hardcoded ``"__module__"`` instead; downstream reference-graph
    code matches on that literal. The parameter stays on the signature
    so a future change that actually threads the prefix through has a
    place to plug in without touching every caller.

    Args:
        symbols: Iterable of Symbol dataclass objects. Only ``function``
            and ``method`` kinds contribute enclosing scopes; other
            kinds are dropped here.
        content_str: Source code text.
        language: Language identifier. Only ``"python"`` is supported
            today; other values return an empty list, matching the
            Python implementation's behaviour.
        repo_name: Accepted for forward compatibility with potential
            per-repo module-id scoping. Not used today.

    Returns:
        List of CallSite records.
    """
    del repo_name
    ranges = [
        (sym.symbol_id, int(sym.byte_offset), int(sym.byte_length))
        for sym in symbols
        if getattr(sym, "kind", None) in ("function", "method")
    ]
    raw = _rust_extract_call_sites(ranges, content_str, language)
    return [CallSite(caller_symbol_id=caller, callee_name=callee, line=int(line)) for caller, callee, line in raw]
