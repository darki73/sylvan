"""Patch parso grammar to support PEP 695 type parameters.

Parso 0.8.6 doesn't include type_params in its Python 3.12+ grammar,
causing class definitions like ``class Foo[T]:`` to be parsed as
error nodes. This module patches the grammar at import time so jedi
can resolve methods on generic classes.

Call ``ensure_patched()`` before creating any jedi.Script instances.
"""

from __future__ import annotations

from pathlib import Path

_patched = False

_TYPE_PARAMS_RULES = (
    "type_params: '[' type_param (',' type_param)* [','] ']'\n"
    "type_param: NAME [type_param_bound] | '*' NAME | '**' NAME\n"
    "type_param_bound: ':' test\n"
    "type_stmt: 'type' NAME [type_params] '=' test\n\n"
)


def ensure_patched() -> None:
    """Patch parso grammars for PEP 695 support if not already patched."""
    global _patched
    if _patched:
        return

    try:
        import parso
        from parso.grammar import PythonGrammar, _loaded_grammars
        from parso.utils import PythonVersionInfo
    except ImportError:
        return

    grammar_dir = Path(parso.__file__).parent / "python"

    for version in ("312", "313", "314"):
        path = grammar_dir / f"grammar{version}.txt"
        path_str = str(path)
        if not path.exists():
            continue
        if path_str in _loaded_grammars:
            continue

        try:
            bnf = path.read_text()
        except OSError:
            continue

        if "type_params" in bnf:
            continue

        patched = _patch_grammar(bnf)

        major, minor = int(version[0]), int(version[1:])
        grammar = PythonGrammar(PythonVersionInfo(major, minor), patched)
        _loaded_grammars[path_str] = grammar

    _patch_class_node()
    _patched = True


def _patch_class_node() -> None:
    """Patch parso's Class.get_super_arglist to handle type_params.

    The original uses hardcoded children[2] and children[3] which breaks
    when type_params are present, shifting the '(' to a later position.
    """
    try:
        from parso.python.tree import Class
    except ImportError:
        return

    def get_super_arglist(self):  # type: ignore[no-untyped-def]
        for i, child in enumerate(self.children):
            if hasattr(child, "value") and child.value == "(":
                if (
                    i + 1 < len(self.children)
                    and hasattr(self.children[i + 1], "value")
                    and self.children[i + 1].value == ")"
                ):
                    return None
                return self.children[i + 1] if i + 1 < len(self.children) else None
        return None

    Class.get_super_arglist = get_super_arglist


def _patch_grammar(bnf: str) -> str:
    """Apply PEP 695 patches to a parso BNF grammar string."""
    result = bnf.replace(
        "classdef: 'class' NAME ['(' [arglist] ')'] ':' suite",
        _TYPE_PARAMS_RULES + "classdef: 'class' NAME [type_params] ['(' [arglist] ')'] ':' suite",
    )

    if "func_type_comment" in result:
        result = result.replace(
            "funcdef: 'def' NAME parameters ['->' test] ':' [func_type_comment] suite",
            "funcdef: 'def' NAME [type_params] parameters ['->' test] ':' [func_type_comment] suite",
        )
    else:
        result = result.replace(
            "funcdef: 'def' NAME parameters ['->' test] ':' suite",
            "funcdef: 'def' NAME [type_params] parameters ['->' test] ':' suite",
        )

    if "type_stmt" not in result:
        result = result.replace(
            "classdef | decorated | async_stmt",
            "classdef | decorated | async_stmt | type_stmt",
        )

    return result
