"""Built-in language registrations.

One file replacing the per-language plugin modules. Each built-in
language has a shim that delegates import extraction and resolution to
the Rust pipeline via ``sylvan._rust``. Complexity patterns and
receiver-stripping logic stay in Python because no production code
consumes them any more - only the public registry API survives for
external extensions that still plug in via ``@register``.
"""

from __future__ import annotations

import re

from sylvan._rust import extract_imports as _rust_extract_imports
from sylvan._rust import generate_candidates as _rust_generate_candidates
from sylvan.indexing.source_code.language_specs import LanguageSpec


class _RustImports:
    """Shim that forwards ``extract_imports`` to the Rust extractor."""

    def __init__(self, language: str) -> None:
        self._language = language

    def extract_imports(self, content: str) -> list[dict]:
        try:
            return list(_rust_extract_imports(content, "", self._language))
        except Exception:
            return []


class _RustResolver:
    """Shim that forwards ``generate_candidates`` to the Rust resolver."""

    def __init__(self, language: str) -> None:
        self._language = language

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context,
    ) -> list[str]:
        psr4 = context.psr4_mappings if context is not None else None
        ts = context.tsconfig_aliases if context is not None else None
        try:
            return list(_rust_generate_candidates(specifier, source_path, self._language, psr4, ts))
        except Exception:
            return []


_PY_DECISION = re.compile(r"\b(if|elif|for|while|except|and|or|assert)\b|\bif\s+.*\s+else\s+")
_JS_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?\?|\?(?=[^:])")
_RUBY_DECISION = re.compile(r"\b(if|elif|for|while|except|and|or|assert)\b|\bif\s+.*\s+else\s+")
_RUST_DECISION = re.compile(r"\b(if|for|while|loop|match)\b|=>")
_PHP_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")
_JAVA_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")
_CSHARP_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")
_GO_DECISION = re.compile(r"\b(if|for|case|select)\b|&&|\|\|")
_C_DECISION = re.compile(r"\b(if|elif|for|while|case|catch|except)\b|&&|\|\||(?<!\w)and\b|(?<!\w)or\b")
_SWIFT_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")


def _passthrough(params_str: str) -> str:
    return params_str


def _strip_python_receiver(params_str: str) -> str:
    if params_str in ("self", "cls"):
        return ""
    for prefix in ("self,", "cls,"):
        if params_str.startswith(prefix):
            return params_str[len(prefix) :].strip()
    return params_str


def _strip_rust_receiver(params_str: str) -> str:
    for prefix in ("&mut self,", "&self,", "mut self,", "self,"):
        if params_str.startswith(prefix):
            return params_str[len(prefix) :].strip()
    if params_str in ("&self", "&mut self", "self", "mut self"):
        return ""
    return params_str


class _Complexity:
    """Bundle of per-language complexity hints.

    Attributes are read by the public ``get_complexity_provider`` hook
    that downstream callers (none in-tree today) can use to wire their
    own complexity scoring on top of the extracted symbols.
    """

    def __init__(self, decision_pattern, uses_braces: bool, strip_receiver) -> None:
        self.decision_pattern = decision_pattern
        self.uses_braces = uses_braces
        self._strip = strip_receiver

    def strip_receiver(self, params_str: str) -> str:
        return self._strip(params_str)


def _make_language(
    name: str,
    ts_language: str,
    extensions: list[str],
    *,
    imports: bool = False,
    resolver: bool = False,
    complexity: _Complexity | None = None,
):
    """Build a plugin instance + register it.

    Returns the instance so alias registrations can share identity
    through the public ``register_alias`` hook.
    """
    from sylvan.indexing.languages import register

    methods: dict = {}
    if imports:
        shim = _RustImports(name)
        methods["extract_imports"] = shim.extract_imports
    if resolver:
        shim = _RustResolver(name)
        methods["generate_candidates"] = shim.generate_candidates
    if complexity is not None:
        methods["decision_pattern"] = complexity.decision_pattern
        methods["uses_braces"] = complexity.uses_braces
        methods["strip_receiver"] = lambda self, p, _f=complexity.strip_receiver: _f(p)

    cls = type(f"_{name.title()}Plugin", (), methods)
    spec = LanguageSpec(
        ts_language=ts_language,
        symbol_node_types={},
        name_fields={},
    )
    register(name=name, extensions=extensions, spec=spec)(cls)
    return cls


def _register_alias(
    primary_cls,
    name: str,
    ts_language: str,
    extensions: list[str],
) -> None:
    from sylvan.indexing.languages import register_alias

    spec = LanguageSpec(
        ts_language=ts_language,
        symbol_node_types={},
        name_fields={},
    )
    register_alias(name=name, extensions=extensions, spec=spec, plugin_cls=primary_cls)


_PYTHON_COMPLEXITY = _Complexity(_PY_DECISION, False, _strip_python_receiver)
_JS_COMPLEXITY = _Complexity(_JS_DECISION, True, _passthrough)
_RUBY_COMPLEXITY = _Complexity(_RUBY_DECISION, False, _passthrough)
_RUST_COMPLEXITY = _Complexity(_RUST_DECISION, True, _strip_rust_receiver)
_PHP_COMPLEXITY = _Complexity(_PHP_DECISION, True, _passthrough)
_JAVA_COMPLEXITY = _Complexity(_JAVA_DECISION, True, _passthrough)
_CSHARP_COMPLEXITY = _Complexity(_CSHARP_DECISION, True, _passthrough)
_GO_COMPLEXITY = _Complexity(_GO_DECISION, True, _passthrough)
_C_COMPLEXITY = _Complexity(_C_DECISION, True, _passthrough)
_SWIFT_COMPLEXITY = _Complexity(_SWIFT_DECISION, True, _passthrough)


def _register_all() -> None:
    python_cls = _make_language(
        "python",
        "python",
        [".py", ".pyi", ".pyx"],
        imports=True,
        resolver=True,
        complexity=_PYTHON_COMPLEXITY,
    )
    del python_cls

    js_cls = _make_language(
        "javascript",
        "javascript",
        [".js", ".mjs", ".cjs"],
        imports=True,
        resolver=True,
        complexity=_JS_COMPLEXITY,
    )
    _register_alias(js_cls, "typescript", "typescript", [".ts"])
    _register_alias(js_cls, "tsx", "tsx", [".tsx"])
    _register_alias(js_cls, "jsx", "javascript", [".jsx"])

    _make_language(
        "php",
        "php",
        [".php"],
        imports=True,
        resolver=True,
        complexity=_PHP_COMPLEXITY,
    )

    _make_language(
        "blade",
        "php",
        [".blade.php"],
        imports=True,
        resolver=True,
    )

    _make_language(
        "csharp",
        "csharp",
        [".cs"],
        imports=True,
        resolver=True,
        complexity=_CSHARP_COMPLEXITY,
    )

    c_cls = _make_language(
        "c",
        "c",
        [".c", ".h"],
        imports=True,
        resolver=True,
        complexity=_C_COMPLEXITY,
    )
    _register_alias(c_cls, "cpp", "cpp", [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"])

    _make_language(
        "go",
        "go",
        [".go"],
        imports=True,
        resolver=True,
        complexity=_GO_COMPLEXITY,
    )

    java_cls = _make_language(
        "java",
        "java",
        [".java"],
        imports=True,
        resolver=True,
        complexity=_JAVA_COMPLEXITY,
    )
    _register_alias(java_cls, "kotlin", "kotlin", [".kt", ".kts"])

    _make_language(
        "ruby",
        "ruby",
        [".rb", ".rake", ".gemspec"],
        imports=True,
        resolver=True,
        complexity=_RUBY_COMPLEXITY,
    )

    _make_language(
        "rust",
        "rust",
        [".rs"],
        imports=True,
        resolver=True,
        complexity=_RUST_COMPLEXITY,
    )

    _make_language(
        "swift",
        "swift",
        [".swift"],
        imports=True,
        complexity=_SWIFT_COMPLEXITY,
    )

    _make_language("scss", "scss", [".scss", ".sass"], imports=True)
    _make_language("less", "css", [".less"], imports=True)
    _make_language("stylus", "css", [".styl"], imports=True)

    for name, exts in (
        ("scala", [".scala", ".sc"]),
        ("dart", [".dart"]),
        ("bash", [".sh", ".bash", ".zsh"]),
        ("elixir", [".ex", ".exs"]),
        ("lua", [".lua"]),
        ("perl", [".pl", ".pm", ".t"]),
        ("haskell", [".hs", ".lhs"]),
        ("erlang", [".erl", ".hrl"]),
        ("gleam", [".gleam"]),
        ("hcl", [".hcl", ".tf", ".tfvars"]),
        ("sql", [".sql"]),
        ("graphql", [".graphql", ".gql"]),
        ("proto", [".proto"]),
        ("objc", [".m", ".mm"]),
        ("groovy", [".groovy", ".gradle"]),
        ("fortran", [".f90", ".f95", ".f03", ".f08", ".for", ".f"]),
        ("nix", [".nix"]),
        ("gdscript", [".gd"]),
        ("r", [".r", ".R"]),
        ("julia", [".jl"]),
        ("css", [".css"]),
    ):
        _make_language(name, name, exts)


_register_all()
