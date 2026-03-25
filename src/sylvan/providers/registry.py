"""Provider registry -- auto-discovery via @register_provider decorator."""

from collections.abc import Callable

_SUMMARY_PROVIDERS: dict[str, type] = {}
_EMBEDDING_PROVIDERS: dict[str, type] = {}


def register_summary_provider(name: str) -> Callable[[type], type]:
    """Register a summary provider class.

    Args:
        name: Provider name matching config value (e.g., 'ollama', 'heuristic').

    Returns:
        Decorator that registers the provider class.
    """

    def decorator(cls: type) -> type:
        """Store the provider class in the summary registry."""
        _SUMMARY_PROVIDERS[name] = cls
        return cls

    return decorator


def register_embedding_provider(name: str) -> Callable[[type], type]:
    """Register an embedding provider class.

    Args:
        name: Provider name matching config value.

    Returns:
        Decorator that registers the provider class.
    """

    def decorator(cls: type) -> type:
        """Store the provider class in the embedding registry."""
        _EMBEDDING_PROVIDERS[name] = cls
        return cls

    return decorator


def get_summary_provider_class(name: str) -> type | None:
    """Look up a summary provider class by name.

    Args:
        name: Provider name from configuration.

    Returns:
        The provider class, or None.
    """
    return _SUMMARY_PROVIDERS.get(name)


def get_embedding_provider_class(name: str) -> type | None:
    """Look up an embedding provider class by name.

    Args:
        name: Provider name from configuration.

    Returns:
        The provider class, or None.
    """
    return _EMBEDDING_PROVIDERS.get(name)


def list_providers() -> dict[str, list[str]]:
    """List all registered providers.

    Returns:
        Dict with 'summary' and 'embedding' keys mapping to provider name lists.
    """
    return {
        "summary": sorted(_SUMMARY_PROVIDERS.keys()),
        "embedding": sorted(_EMBEDDING_PROVIDERS.keys()),
    }
