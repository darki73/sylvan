"""Application context -- dependency injection for the ORM and tools.

Two layers:
- App state: module-level singleton holding backend, config, session, cache.
  Set once at startup. Shared by all tasks.
- Request state: contextvar holding per-request identity map.
  Set by middleware and dispatch for each request/tool call.

get_context() merges both into a SylvanContext for the ORM.
"""

import contextvars
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any

from sylvan.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SylvanContext:
    """Merged view of app state + request state.

    Attributes:
        backend: The async storage backend.
        config: The application configuration.
        session: The session tracker.
        cache: The query cache instance.
        identity_map: Per-request identity map for deduplicating loaded model instances.
    """

    backend: Any = None
    config: Any = None
    session: Any = None
    cache: Any = None
    identity_map: Any = None


@dataclass
class _AppState:
    """Process-wide singletons. Not a contextvar."""

    backend: Any = None
    config: Any = None
    session: Any = None
    cache: Any = None


_app_state = _AppState()

_identity_map_var: contextvars.ContextVar[Any] = contextvars.ContextVar("sylvan_identity_map", default=None)

# Legacy contextvar kept for backward compatibility with tests and CLI
_current_context: contextvars.ContextVar[SylvanContext | None] = contextvars.ContextVar("sylvan_context", default=None)


def init_app_state(*, backend: Any, config: Any = None, session: Any = None, cache: Any = None) -> None:
    """Initialize the process-wide app state. Called once at startup.

    Args:
        backend: The async storage backend.
        config: The application configuration.
        session: The session tracker.
        cache: The query cache instance.
    """
    _app_state.backend = backend
    _app_state.config = config
    _app_state.session = session
    _app_state.cache = cache


def get_context() -> SylvanContext:
    """Get the current sylvan context.

    Merges the process-wide app state with the per-request identity map.
    Falls back to the legacy contextvar if set (tests, CLI).

    Returns:
        The active SylvanContext.
    """
    legacy = _current_context.get()
    if legacy is not None:
        return legacy

    if _app_state.backend is not None:
        from sylvan.database.orm.runtime.identity_map import IdentityMap

        return SylvanContext(
            backend=_app_state.backend,
            config=_app_state.config,
            session=_app_state.session,
            cache=_app_state.cache,
            identity_map=_identity_map_var.get() or IdentityMap(),
        )

    return _build_default_context()


def set_context(ctx: SylvanContext) -> contextvars.Token:
    """Set the legacy context for the current execution scope.

    Used by tests and CLI commands that set up their own context.

    Args:
        ctx: The context to make current.

    Returns:
        A token that can be used to reset to the previous context.
    """
    return _current_context.set(ctx)


def reset_context(token: contextvars.Token) -> None:
    """Reset the legacy context to its previous value.

    Args:
        token: The token returned by set_context().
    """
    _current_context.reset(token)


def set_identity_map(identity_map: Any) -> contextvars.Token:
    """Set the per-request identity map.

    Args:
        identity_map: The IdentityMap for this request.

    Returns:
        A token to reset it.
    """
    return _identity_map_var.set(identity_map)


def reset_identity_map(token: contextvars.Token) -> None:
    """Reset the per-request identity map.

    Args:
        token: The token returned by set_identity_map().
    """
    _identity_map_var.reset(token)


@asynccontextmanager
async def using_context(ctx: SylvanContext) -> AsyncIterator[SylvanContext]:
    """Async context manager for setting a temporary legacy context.

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
    """Sync context manager for setting a temporary legacy context.

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
    """Await all background tasks spawned via create_task.

    Call before disconnecting the backend in CLI commands to ensure
    fire-and-forget tasks complete before the event loop shuts down.
    """
    import asyncio

    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _build_default_context() -> SylvanContext:
    """Build a context from existing global singletons.

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
