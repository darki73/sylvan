"""Server lifecycle manager that owns all background tasks.

All background tasks (heartbeat, WebSocket, dashboard, leader pings)
are spawned through this manager. When the server shuts down, every
task is cancelled automatically via asyncio.TaskGroup.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine

from sylvan.logging import get_logger

logger = get_logger(__name__)

_lifecycle: ServerLifecycle | None = None


class ServerLifecycle:
    """Manages background task lifetimes for the sylvan server.

    All tasks spawned through this manager are guaranteed to be
    cancelled when the context exits, regardless of how the server
    shuts down (stdin close, signal, crash).

    Example::

        async with ServerLifecycle() as lifecycle:
            lifecycle.spawn(heartbeat_loop(), name="heartbeat")
            lifecycle.spawn(ws_ping_loop(), name="pings")
            await run_transport()
    """

    def __init__(self) -> None:
        self._task_group: asyncio.TaskGroup | None = None
        self._tasks: list[asyncio.Task] = []
        self._entered = False

    async def __aenter__(self) -> ServerLifecycle:
        global _lifecycle
        self._task_group = asyncio.TaskGroup()
        await self._task_group.__aenter__()
        self._entered = True
        _lifecycle = self
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        global _lifecycle
        _lifecycle = None
        self._entered = False

        await self._graceful_shutdown()

        for task in self._tasks:
            if not task.done():
                task.cancel()

        try:  # noqa: SIM105 -- contextlib.suppress doesn't work with except*
            await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        except* BaseException:  # noqa: S110
            pass

        logger.debug("lifecycle_shutdown", tasks_cancelled=len(self._tasks))

    async def _graceful_shutdown(self) -> None:
        """Broadcast step-down and release the cluster lock if this is the leader.

        Called before task cancellation so followers can promote immediately
        instead of waiting for the heartbeat to detect the dead PID.
        """
        import contextlib

        from sylvan.cluster.state import get_cluster_state

        state = get_cluster_state()
        if state.is_leader:
            with contextlib.suppress(Exception):
                from sylvan.cluster.websocket import broadcast_step_down

                await broadcast_step_down()

            with contextlib.suppress(Exception):
                from sylvan.cluster.discovery import release_leadership

                await release_leadership()

    def spawn(self, coro: Coroutine, *, name: str | None = None) -> asyncio.Task:
        """Spawn a background task owned by this lifecycle.

        Args:
            coro: The coroutine to run.
            name: Optional task name for debugging.

        Returns:
            The created asyncio.Task.
        """
        if not self._entered or self._task_group is None:
            raise RuntimeError("ServerLifecycle is not entered. Use 'async with'.")
        task = self._task_group.create_task(coro, name=name)
        self._tasks.append(task)
        logger.debug("task_spawned", name=name or "unnamed", total=len(self._tasks))
        return task


def get_lifecycle() -> ServerLifecycle | None:
    """Get the active server lifecycle, or None.

    Returns:
        The singleton ServerLifecycle if entered, or None.
    """
    return _lifecycle
