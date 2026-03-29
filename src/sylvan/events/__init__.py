"""Sylvan event bus.

Process-wide pub/sub for internal events. Any module can emit events,
any module can subscribe. The dashboard WebSocket is one consumer,
but extensions, plugins, and other subsystems can subscribe too.

Usage::

    from sylvan.events import emit, on, off

    # Subscribe
    def on_tool_call(data):
        print(f"Tool called: {data['name']}")

    on("tool_call", on_tool_call)

    # Emit from anywhere
    emit("tool_call", {"name": "search_symbols", "duration_ms": 42})

    # Async subscribers work too
    async def on_index_complete(data):
        await notify_dashboard(data)

    on("index_complete", on_index_complete)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from sylvan.logging import get_logger

logger = get_logger(__name__)

_sync_listeners: dict[str, set[Callable]] = defaultdict(set)
_async_listeners: dict[str, set[Callable]] = defaultdict(set)
_queues: set[asyncio.Queue] = set()


def on(event: str, handler: Callable) -> None:
    """Subscribe to an event.

    Args:
        event: Event name to listen for.
        handler: Callback function. Can be sync or async.
    """
    if asyncio.iscoroutinefunction(handler):
        _async_listeners[event].add(handler)
    else:
        _sync_listeners[event].add(handler)


def off(event: str, handler: Callable) -> None:
    """Unsubscribe from an event.

    Args:
        event: Event name.
        handler: The handler to remove.
    """
    _sync_listeners[event].discard(handler)
    _async_listeners[event].discard(handler)


def emit(event: str, data: Any = None) -> None:
    """Emit an event to all subscribers.

    Sync handlers are called immediately. Async handlers are scheduled
    on the running event loop. Queue consumers receive a copy.

    Args:
        event: Event name.
        data: Optional payload.
    """
    for handler in _sync_listeners.get(event, ()):
        try:
            handler(data)
        except Exception as exc:
            logger.debug("event_handler_error", event_name=event, error=str(exc))

    for handler in _async_listeners.get(event, ()):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(handler(data))
        except RuntimeError:
            pass
        except Exception as exc:
            logger.debug("event_handler_error", event_name=event, error=str(exc))

    if _queues:
        msg = {"type": event, "data": data}
        dead = []
        for q in _queues:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _queues.discard(q)


def create_queue(maxsize: int = 256) -> asyncio.Queue:
    """Create an event queue that receives all emitted events.

    Used by the dashboard WebSocket to stream events to browsers.

    Args:
        maxsize: Maximum queue depth before events are dropped.

    Returns:
        An asyncio.Queue that receives all events.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    _queues.add(q)
    return q


def remove_queue(q: asyncio.Queue) -> None:
    """Remove an event queue.

    Args:
        q: The queue to stop receiving events.
    """
    _queues.discard(q)
