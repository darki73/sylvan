"""Language specifications for tree-sitter symbol extraction."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class LanguageSpec:
    """Configuration for extracting symbols from a specific language.

    Attributes:
        ts_language: Tree-sitter language name.
        symbol_node_types: Mapping of AST node types to symbol kinds.
        name_fields: Mapping of AST node types to field names for extracting the symbol name.
        param_fields: Mapping of node types to parameter field names.
        return_type_fields: Mapping of node types to return type field names.
        docstring_strategy: Strategy for extracting docstrings.
        decorator_node_type: AST node type for decorators/annotations, if applicable.
        container_node_types: AST node types that contain nested symbols (e.g., class bodies).
        constant_patterns: AST patterns for constant detection.
        type_patterns: AST patterns for type definition detection.
    """

    ts_language: str
    symbol_node_types: dict[str, str]
    name_fields: dict[str, str]
    param_fields: dict[str, str] = field(default_factory=dict)
    return_type_fields: dict[str, str] = field(default_factory=dict)
    docstring_strategy: str = "preceding_comment"  # preceding_comment | next_sibling_string
    decorator_node_type: str | None = None
    container_node_types: list[str] = field(default_factory=list)
    constant_patterns: list[str] = field(default_factory=list)
    type_patterns: list[str] = field(default_factory=list)


# Extension -> language mapping. Used by detect_language() and file discovery.
# The canonical source of truth is now the language plugins (which register
# extensions via the @register decorator), but this dict is kept for backward
# compatibility with code that imports it directly.
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".pyx": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".h": "c",
    ".cs": "c_sharp",
    ".swift": "swift",
    ".rb": "ruby",
    ".rake": "ruby",
    ".gemspec": "ruby",
    ".php": "php",
    ".scala": "scala",
    ".sc": "scala",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".t": "perl",
    ".sh": "bash",
    ".bash": "bash",
    ".hs": "haskell",
    ".lhs": "haskell",
    ".jl": "julia",
    ".r": "r",
    ".R": "r",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".f90": "fortran",
    ".f95": "fortran",
    ".f03": "fortran",
    ".f08": "fortran",
    ".f": "fortran",
    ".for": "fortran",
    ".fpp": "fortran",
    ".sql": "sql",
    ".m": "objc",
    ".mm": "objc",
    ".proto": "proto",
    ".tf": "hcl",
    ".hcl": "hcl",
    ".tfvars": "hcl",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".nix": "nix",
    ".vue": "vue",
    ".gd": "gdscript",
    ".gleam": "gleam",
    ".css": "css",
    ".scss": "scss",
    ".sass": "scss",
    ".less": "less",
    ".styl": "stylus",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".asm": "asm",
    ".s": "asm",
    ".S": "asm",
    ".inc": "asm",
    ".xml": "xml",
    ".xul": "xml",
    ".json": "json",
}

CUSTOM_EXTRACTION_LANGUAGES: frozenset[str] = frozenset(
    {
        "asm",
        "json",
        "less",
        "scss",
        "stylus",
        "toml",
        "vue",
        "yaml",
    }
)
"""Languages where tree-sitter extraction may be incomplete."""


def _ensure_plugins_loaded() -> None:
    """Ensure language plugins are loaded before registry access."""
    from sylvan.indexing.languages import _load_builtin_languages

    _load_builtin_languages()


def detect_language(filename: str) -> str | None:
    """Detect language from file extension.

    Args:
        filename: File name or relative path.

    Returns:
        Language identifier string, or None if unrecognized.
    """
    _ensure_plugins_loaded()
    from sylvan.indexing.source_code.language_registry import get_language_for_extension

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return get_language_for_extension(ext) or LANGUAGE_EXTENSIONS.get(ext)


def get_spec(language: str) -> LanguageSpec | None:
    """Get the extraction spec for a language.

    Args:
        language: Language identifier (e.g., "python", "typescript").

    Returns:
        LanguageSpec for the language, or None if unsupported.
    """
    _ensure_plugins_loaded()
    from sylvan.indexing.source_code.language_registry import get_language_spec

    return get_language_spec(language)
