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

    On a follower instance, the job is proxied to the leader over
    WebSocket instead of being enqueued locally.

    Args:
        job_type: Registered worker type name.
        key: Optional deduplication key. Jobs with the same key are
            not queued twice.
        **kwargs: Arguments passed to the worker's handle method.

    Returns:
        A Future that resolves with the worker's return value.
    """
    if _is_follower():
        return await _proxy_submit_to_leader(job_type, key, kwargs)

    runner = get_runner()
    future = asyncio.get_event_loop().create_future()
    job = Job(job_type=job_type, kwargs=kwargs, key=key, future=future)
    await runner.enqueue(job)
    return future


def _is_follower() -> bool:
    """Check if this instance is a cluster follower."""
    try:
        from sylvan.cluster.state import get_cluster_state

        return get_cluster_state().is_follower
    except Exception:
        return False


async def _proxy_submit_to_leader(
    job_type: str,
    key: str | None,
    kwargs: dict,
) -> asyncio.Future:
    """Proxy a job submission to the leader via WebSocket.

    Args:
        job_type: Registered worker type name.
        key: Optional deduplication key.
        kwargs: Arguments passed to the worker's handle method.

    Returns:
        A Future that resolves with the leader's result.
    """
    from sylvan.cluster import protocol
    from sylvan.cluster.websocket import _follower_ws, _pending_writes
    from sylvan.logging import get_logger

    logger = get_logger(__name__)

    if _follower_ws is None:
        logger.warning("job_proxy_no_connection", job_type=job_type, key=key)
        raise ConnectionError("Not connected to leader, cannot proxy job submission.")

    request_id = protocol.make_id()
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _pending_writes[request_id] = future

    try:
        await _follower_ws.send(protocol.job_submit_request(job_type, key, kwargs, request_id))
        logger.info("job_proxied_to_leader", job_type=job_type, key=key)
        result = await asyncio.wait_for(future, timeout=600)
    except TimeoutError as exc:
        _pending_writes.pop(request_id, None)
        raise TimeoutError(f"Leader did not complete job {job_type} within 600 seconds.") from exc
    except Exception:
        _pending_writes.pop(request_id, None)
        raise

    # Wrap the result in a resolved future for API compatibility
    resolved: asyncio.Future = asyncio.get_running_loop().create_future()
    resolved.set_result(result)
    return resolved


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
