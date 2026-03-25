"""Language spec registry -- auto-discovery via @register_language decorator."""

from collections.abc import Callable

_LANGUAGES: dict[str, object] = {}
_EXTENSION_MAP: dict[str, str] = {}


def register_language(name: str, extensions: list[str]) -> Callable:
    """Register a language spec for given file extensions.

    Use as a decorator on LanguageSpec instances or as a function call.

    Args:
        name: Language name (e.g., 'python', 'typescript').
        extensions: File extensions this language handles (e.g., ['.py', '.pyi']).

    Returns:
        Decorator that registers the language spec.
    """

    def decorator(spec: object) -> object:
        """Store the spec in the registry and map extensions to this language."""
        _LANGUAGES[name] = spec
        for ext in extensions:
            _EXTENSION_MAP[ext.lower()] = name
        return spec

    return decorator


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


def list_supported_languages() -> dict[str, list[str]]:
    """List all registered languages and their extensions.

    Returns:
        Dict mapping language names to their supported extensions.
    """
    result: dict[str, list[str]] = {}
    for ext, name in sorted(_EXTENSION_MAP.items()):
        result.setdefault(name, []).append(ext)
    return result
