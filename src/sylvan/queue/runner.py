"""Queue runner - priority-based FIFO job processor."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sylvan.events import emit
from sylvan.logging import get_logger
from sylvan.queue.job import Job, JobStatus

if TYPE_CHECKING:
    from sylvan.queue.worker.base import BaseWorker

logger = get_logger(__name__)


class QueueRunner:
    """Processes jobs from multiple workers in priority order.

    Workers are sorted by priority (lower = higher). The runner
    checks each worker's queue in order and processes the first
    available job. If all queues are empty, it waits for a
    notification signal.
    """

    def __init__(self) -> None:
        self._workers: list[BaseWorker] = []
        self._notify = asyncio.Event()
        self._running = False
        self._recent_jobs: list[dict] = []

    def add_worker(self, worker: BaseWorker) -> None:
        """Register a worker and sort by priority.

        Args:
            worker: The worker instance to add.
        """
        self._workers.append(worker)
        self._workers.sort(key=lambda w: w.priority)
        logger.info("worker_registered", job_type=worker.job_type, priority=worker.priority)

    async def enqueue(self, job: Job) -> None:
        """Add a job to the appropriate worker's queue.

        Checks for duplicates before enqueueing. Wakes the runner
        if it's waiting for work.

        Args:
            job: The job to enqueue.

        Raises:
            ValueError: If no worker is registered for the job type.
        """
        worker = self._find_worker(job.job_type)
        if worker is None:
            raise ValueError(f"No worker registered for job type: {job.job_type}")

        if job.key and worker.is_duplicate(job.key):
            logger.debug("job_deduplicated", job_type=job.job_type, key=job.key)
            if job.future and not job.future.done():
                job.future.set_result({"deduplicated": True, "key": job.key})
            return

        await worker.queue.put(job)
        logger.debug("job_enqueued", job_id=job.id, job_type=job.job_type, key=job.key)
        emit(
            "job_enqueued",
            {
                "job_id": job.id,
                "job_type": job.job_type,
                "key": job.key,
                "queue_size": worker.pending_count,
            },
        )
        self._notify.set()

    async def run(self) -> None:
        """Main loop. Processes jobs in priority order until cancelled."""
        self._running = True
        logger.info("queue_runner_started", workers=len(self._workers))

        try:
            while self._running:
                job, worker = await self._next_job()
                await self._execute(job, worker)
        except asyncio.CancelledError:
            logger.info("queue_runner_stopping")
            raise

    async def cancel_by_key(self, key: str) -> int:
        """Cancel all pending jobs with the given key across all workers.

        Args:
            key: The deduplication key.

        Returns:
            Total number of jobs cancelled.
        """
        total = 0
        for worker in self._workers:
            total += worker.cancel_by_key(key)
        return total

    def status(self) -> dict:
        """Get current queue status for dashboard display.

        Returns:
            Dict with per-worker queue sizes and current jobs.
        """
        workers = []
        for w in self._workers:
            entry: dict[str, Any] = {
                "job_type": w.job_type,
                "priority": w.priority,
                "pending": w.pending_count,
                "current": None,
            }
            if w.current_job:
                entry["current"] = {
                    "job_id": w.current_job.id,
                    "key": w.current_job.key,
                    "status": w.current_job.status.value,
                    "progress": w.current_job.progress,
                }
            workers.append(entry)
        return {
            "workers": workers,
            "recent": self._recent_jobs[-10:],
        }

    async def _next_job(self) -> tuple[Job, BaseWorker]:
        """Wait for and return the next job in priority order.

        Checks each worker's queue from highest to lowest priority.
        If all empty, waits for the notify event.

        Returns:
            Tuple of (job, worker).
        """
        while True:
            for worker in self._workers:
                try:
                    job = worker.queue.get_nowait()
                    return job, worker
                except asyncio.QueueEmpty:
                    continue
            self._notify.clear()
            await self._notify.wait()

    async def _execute(self, job: Job, worker: BaseWorker) -> None:
        """Run a job on its worker, handle result/errors.

        Args:
            job: The job to execute.
            worker: The worker that handles this job type.
        """
        job.status = JobStatus.RUNNING
        worker._current_job = job
        logger.info("job_started", job_id=job.id, job_type=job.job_type, key=job.key)
        emit(
            "job_started",
            {
                "job_id": job.id,
                "job_type": job.job_type,
                "key": job.key,
            },
        )

        try:
            result = await worker.handle(job)
            job.status = JobStatus.COMPLETE
            if job.future and not job.future.done():
                job.future.set_result(result)
            logger.info("job_complete", job_id=job.id, job_type=job.job_type, key=job.key)
            emit(
                "job_complete",
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "key": job.key,
                    "result": result if isinstance(result, dict) else None,
                },
            )
            self._recent_jobs.append(
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "key": job.key,
                    "status": "complete",
                }
            )
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            if job.future and not job.future.done():
                job.future.cancel()
            raise
        except Exception as exc:
            job.status = JobStatus.FAILED
            if job.future and not job.future.done():
                job.future.set_exception(exc)
            logger.warning("job_failed", job_id=job.id, job_type=job.job_type, error=str(exc))
            emit(
                "job_failed",
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "key": job.key,
                    "error": str(exc),
                },
            )
            self._recent_jobs.append(
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "key": job.key,
                    "status": "failed",
                    "error": str(exc),
                }
            )
        finally:
            worker._current_job = None
            if len(self._recent_jobs) > 50:
                self._recent_jobs = self._recent_jobs[-50:]

    def _find_worker(self, job_type: str) -> BaseWorker | None:
        """Find the worker for a job type.

        Args:
            job_type: The job type string.

        Returns:
            The matching worker, or None.
        """
        for w in self._workers:
            if w.job_type == job_type:
                return w
        return None
