"""Language plugin registry with capability-based dispatch.

Extends the base language registry with protocol-aware capability lookups.
Each language registers via the ``@register`` decorator, declaring its
tree-sitter spec and optionally implementing extraction, resolution,
and complexity protocols.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sylvan.indexing.source_code.language_registry import (
    _EXTENSION_MAP,
    _LANGUAGES,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sylvan.indexing.languages.protocols import (
        ComplexityProvider,
        ImportExtractor,
        ImportResolver,
    )
    from sylvan.indexing.source_code.language_specs import LanguageSpec

_IMPORT_EXTRACTORS: dict[str, ImportExtractor] = {}
_IMPORT_RESOLVERS: dict[str, ImportResolver] = {}
_COMPLEXITY_PROVIDERS: dict[str, ComplexityProvider] = {}


def register(
    name: str,
    extensions: list[str],
    spec: LanguageSpec,
) -> Callable:
    """Register a language plugin with its capabilities.

    Use as a class decorator. The class is instantiated once and inspected
    for protocol conformance to determine which capabilities it provides.

    For languages that share a plugin class (e.g. JS/TS share extraction logic),
    use ``register_alias`` after registering the primary language.

    Args:
        name: Language identifier (e.g. ``python``, ``php``).
        extensions: File extensions including the dot (e.g. ``[".py", ".pyi"]``).
        spec: Tree-sitter language spec for symbol extraction.

    Returns:
        Class decorator.
    """

    def decorator(cls: type) -> type:
        from sylvan.indexing.languages.protocols import (
            ComplexityProvider,
            ImportExtractor,
            ImportResolver,
        )

        instance = cls()

        # Register spec and extensions in the base registry.
        _LANGUAGES[name] = spec
        for ext in extensions:
            _EXTENSION_MAP[ext.lower()] = name

        # Register capabilities.
        if isinstance(instance, ImportExtractor):
            _IMPORT_EXTRACTORS[name] = instance
        if isinstance(instance, ImportResolver):
            _IMPORT_RESOLVERS[name] = instance
        if isinstance(instance, ComplexityProvider):
            _COMPLEXITY_PROVIDERS[name] = instance

        # Store the instance for alias registration.
        cls._plugin_instance = instance

        return cls

    return decorator


def register_alias(
    name: str,
    extensions: list[str],
    spec: LanguageSpec,
    plugin_cls: type,
) -> None:
    """Register a language alias that shares another plugin's capabilities.

    Use when multiple languages share extraction/resolution logic but have
    different tree-sitter specs (e.g. TypeScript vs JavaScript).

    Args:
        name: Language identifier for the alias.
        extensions: File extensions for this alias.
        spec: Tree-sitter spec for this alias (can differ from the primary).
        plugin_cls: The decorated plugin class whose instance to reuse.
    """
    from sylvan.indexing.languages.protocols import (
        ComplexityProvider,
        ImportExtractor,
        ImportResolver,
    )

    instance = plugin_cls._plugin_instance

    _LANGUAGES[name] = spec
    for ext in extensions:
        _EXTENSION_MAP[ext.lower()] = name

    if isinstance(instance, ImportExtractor):
        _IMPORT_EXTRACTORS[name] = instance
    if isinstance(instance, ImportResolver):
        _IMPORT_RESOLVERS[name] = instance
    if isinstance(instance, ComplexityProvider):
        _COMPLEXITY_PROVIDERS[name] = instance


def get_import_extractor(language: str) -> ImportExtractor | None:
    """Look up the import extractor for a language.

    Args:
        language: Language name.

    Returns:
        The extractor instance, or None if the language has no import extraction.
    """
    _load_builtin_languages()
    return _IMPORT_EXTRACTORS.get(language)


def get_import_resolver(language: str) -> ImportResolver | None:
    """Look up the import resolver for a language.

    Args:
        language: Language name.

    Returns:
        The resolver instance, or None if the language has no import resolution.
    """
    _load_builtin_languages()
    return _IMPORT_RESOLVERS.get(language)


def get_complexity_provider(language: str) -> ComplexityProvider | None:
    """Look up the complexity provider for a language.

    Args:
        language: Language name.

    Returns:
        The provider instance, or None if the language has no complexity patterns.
    """
    _load_builtin_languages()
    return _COMPLEXITY_PROVIDERS.get(language)


_loaded = False


def _load_builtin_languages() -> None:
    """Import all built-in language modules to trigger registration."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    from sylvan.indexing.languages import (  # noqa: F401
        _tree_sitter_only,
        c_family,
        csharp,
        go,
        java,
        javascript,
        php,
        python,
        ruby,
        rust,
        stylesheets,
        swift,
    )
