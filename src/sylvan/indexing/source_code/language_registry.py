"""Language spec registry -- low-level storage for language specs and extension mappings.

The ``languages`` package populates these dicts via its ``@register`` decorator.
Consumers should use ``language_specs.detect_language`` and ``language_specs.get_spec``
rather than accessing these dicts directly.
"""

from __future__ import annotations

_LANGUAGES: dict[str, object] = {}
_EXTENSION_MAP: dict[str, str] = {}


def get_language_for_extension(ext: str) -> str | None:
    """Look up the language name for a file extension.

    Args:
        ext: File extension including the dot (e.g., '.py').

    Returns:
        Language name, or None if unrecognized.
    """
    return _EXTENSION_MAP.get(ext.lower())


def get_language_spec(name: str) -> object | None:
    """Get the LanguageSpec for a language name.

    Args:
        name: Language name (e.g., 'python').

    Returns:
        The LanguageSpec instance, or None.
    """
    return _LANGUAGES.get(name)
