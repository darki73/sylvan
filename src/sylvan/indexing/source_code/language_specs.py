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


def _ensure_plugins_loaded() -> None:
    """Ensure language plugins are loaded before registry access."""
    from sylvan.indexing.languages import _load_builtin_languages

    _load_builtin_languages()


def detect_language(filename: str) -> str | None:
    """Detect language from file extension.

    Checks compound extensions first (e.g. ``.blade.php``) before
    falling back to the last extension segment.

    Args:
        filename: File name or relative path.

    Returns:
        Language identifier string, or None if unrecognized.
    """
    _ensure_plugins_loaded()
    from sylvan.indexing.source_code.language_registry import get_language_for_extension

    if "." not in filename:
        return None

    basename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    segments = basename.split(".")

    # Try compound extension first (e.g. .blade.php from view.blade.php)
    if len(segments) >= 3:
        compound = "." + ".".join(segments[-2:])
        result = get_language_for_extension(compound)
        if result is not None:
            return result

    ext = "." + segments[-1]
    return get_language_for_extension(ext)


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
