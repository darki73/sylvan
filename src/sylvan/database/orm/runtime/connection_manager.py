"""Backend accessor for the async ORM.

The ORM resolves its storage backend from the application context rather
than managing thread-local SQLite connections directly.  This module
provides a single helper that every ORM layer can import.
"""

from sylvan.database.backends.base import StorageBackend


def get_backend() -> StorageBackend:
    """Get the current storage backend from context.

    Returns:
        The active StorageBackend.

    Raises:
        RuntimeError: If no backend is configured in the context.
    """
    from sylvan.context import get_context

    ctx = get_context()
    if ctx.backend is None:
        raise RuntimeError(
            "No storage backend configured. "
            "Set up a SylvanContext with a backend first."
        )
    return ctx.backend
