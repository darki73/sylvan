"""Model registry -- resolves string references to model classes."""

_registry: dict[str, type] = {}
"""Global mapping from model class name to class object."""


def register_model(cls: type) -> None:
    """Register a model class by name for string-based lookups.

    Args:
        cls: The model class to register.
    """
    _registry[cls.__name__] = cls


def get_model(name: str) -> type:
    """Resolve a model name to its class.

    Args:
        name: The model class name to look up.

    Returns:
        The registered model class.

    Raises:
        KeyError: If the model name is not registered.
    """
    if name not in _registry:
        raise KeyError(f"Model '{name}' not registered. Available: {list(_registry.keys())}")
    return _registry[name]
