"""Application context — dependency injection via contextvars."""

import contextvars
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any

from sylvan.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SylvanContext:
    """Holds all per-request dependencies.

    The async ORM, tool handlers, and all other code access the storage
    backend, config, session, and cache through this context rather than
    global singletons.

    Attributes:
        backend: The async storage backend (SQLiteBackend, future PostgresBackend).
        config: The application configuration.
        session: The session tracker for this request chain.
        cache: The query cache instance.
        identity_map: Per-request identity map for deduplicating loaded model instances.
    """

    backend: Any = None
    config: Any = None
    session: Any = None
    cache: Any = None
    identity_map: Any = None


_current_context: contextvars.ContextVar[SylvanContext | None] = contextvars.ContextVar(
    "sylvan_context", default=None
)


def get_context() -> SylvanContext:
    """Get the current sylvan context.

    Returns:
        The active SylvanContext for the current execution context.

    Raises:
        RuntimeError: If no context has been set.
    """
    ctx = _current_context.get()
    if ctx is not None:
        return ctx
    return _build_default_context()


def set_context(ctx: SylvanContext) -> contextvars.Token:
    """Set the sylvan context for the current execution scope.

    Args:
        ctx: The context to make current.

    Returns:
        A token that can be used to reset to the previous context.
    """
    return _current_context.set(ctx)


def reset_context(token: contextvars.Token) -> None:
    """Reset the context to its previous value.

    Args:
        token: The token returned by set_context().
    """
    _current_context.reset(token)


@asynccontextmanager
async def using_context(ctx: SylvanContext) -> AsyncIterator[SylvanContext]:
    """Async context manager for setting a temporary context.

    Useful in tests to inject mock dependencies and in the server
    dispatch to set per-request context.

    Args:
        ctx: The context to use within the block.

    Yields:
        The context that was set.
    """
    token = set_context(ctx)
    try:
        yield ctx
    finally:
        reset_context(token)


@contextmanager
def using_context_sync(ctx: SylvanContext) -> Generator[SylvanContext, None, None]:
    """Sync context manager for setting a temporary context.

    For use in synchronous code paths (CLI commands, tests).

    Args:
        ctx: The context to use within the block.

    Yields:
        The context that was set.
    """
    token = set_context(ctx)
    try:
        yield ctx
    finally:
        reset_context(token)


async def drain_pending_tasks() -> None:
    """Await all background tasks spawned via ``create_task``.

    Call this before disconnecting the backend in CLI commands to ensure
    fire-and-forget tasks (embeddings, summaries) complete before the
    event loop shuts down.  Safe to call when no tasks are pending.
    """
    import asyncio

    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _build_default_context() -> SylvanContext:
    """Build a context from existing global singletons.

    Provides backward compatibility during the async migration —
    code that doesn't set up a context explicitly still works.

    Returns:
        A SylvanContext populated from global singletons.
    """
    ctx = SylvanContext()

    try:
        from sylvan.config import get_config
        ctx.config = get_config()
    except Exception as exc:
        logger.warning("context_component_failed", component="config", error=str(exc))

    try:
        from sylvan.session.tracker import get_session
        ctx.session = get_session()
    except Exception as exc:
        logger.warning("context_component_failed", component="session", error=str(exc))

    try:
        from sylvan.database.orm.runtime.query_cache import get_query_cache
        ctx.cache = get_query_cache()
    except Exception as exc:
        logger.warning("context_component_failed", component="cache", error=str(exc))

    return ctx
