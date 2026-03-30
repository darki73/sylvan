"""Async job queue with priority-based FIFO processing.

Provides a generic task queue for CPU-heavy or long-running operations
that should not block the MCP event loop. Jobs are processed one at a
time per worker, in priority order across worker types.

Usage::

    from sylvan.queue import submit, get_runner, status

    # Submit and await result (MCP tools)
    future = await submit("index_folder", path="/foo", force=True)
    result = await future

    # Submit fire-and-forget (dashboard WS)
    await submit("index_folder", path="/foo", force=True)

    # Check queue status (dashboard)
    info = status()

    # Start the runner (called by ServerLifecycle)
    runner = get_runner()
    lifecycle.spawn(runner.run(), name="job_queue")
"""

from __future__ import annotations

import asyncio

from sylvan.queue.job import Job
from sylvan.queue.runner import QueueRunner

_runner: QueueRunner | None = None


def get_runner() -> QueueRunner:
    """Get or create the global queue runner.

    Automatically discovers and instantiates all registered workers.

    Returns:
        The singleton QueueRunner instance.
    """
    global _runner
    if _runner is None:
        _runner = QueueRunner()
        _discover_workers()
    return _runner


async def submit(job_type: str, *, key: str | None = None, **kwargs) -> asyncio.Future:
    """Submit a job to the queue.

    Args:
        job_type: Registered worker type name.
        key: Optional deduplication key. Jobs with the same key are
            not queued twice.
        **kwargs: Arguments passed to the worker's handle method.

    Returns:
        A Future that resolves with the worker's return value.
    """
    runner = get_runner()
    future = asyncio.get_event_loop().create_future()
    job = Job(job_type=job_type, kwargs=kwargs, key=key, future=future)
    await runner.enqueue(job)
    return future


async def cancel(key: str) -> int:
    """Cancel all pending jobs with the given key.

    Args:
        key: The deduplication key to cancel.

    Returns:
        Number of jobs cancelled.
    """
    runner = get_runner()
    return await runner.cancel_by_key(key)


def status() -> dict:
    """Get current queue status.

    Returns:
        Dict with per-worker queue sizes and current jobs.
    """
    runner = get_runner()
    return runner.status()


def _discover_workers() -> None:
    """Import worker modules to trigger registration, then instantiate."""
    import sylvan.queue.worker.embedding
    import sylvan.queue.worker.indexing
    import sylvan.queue.worker.library_repair
    import sylvan.queue.worker.summary  # noqa: F401
    from sylvan.queue.registry import get_all_worker_classes

    for cls in get_all_worker_classes().values():
        _runner.add_worker(cls())


__all__ = ["cancel", "get_runner", "status", "submit"]
