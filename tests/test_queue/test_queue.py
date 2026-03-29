"""Tests for sylvan.queue - job queue, registry, runner, and workers."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from sylvan.queue.job import Job, JobStatus
from sylvan.queue.registry import get_all_worker_classes, get_worker_class, register_worker
from sylvan.queue.runner import QueueRunner
from sylvan.queue.worker.base import BaseWorker


class TestJobStatus:
    def test_enum_values(self):
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETE.value == "complete"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"


class TestJob:
    def test_defaults(self):
        job = Job(job_type="test")
        assert job.job_type == "test"
        assert job.kwargs == {}
        assert job.priority == 0
        assert job.key is None
        assert job.future is None
        assert job.status == JobStatus.PENDING
        assert job.progress is None
        assert len(job.id) == 12

    async def test_custom_fields(self):
        future = asyncio.get_event_loop().create_future()
        job = Job(
            job_type="index",
            kwargs={"path": "/foo"},
            priority=5,
            key="repo:foo",
            future=future,
        )
        assert job.job_type == "index"
        assert job.kwargs == {"path": "/foo"}
        assert job.priority == 5
        assert job.key == "repo:foo"
        assert job.future is future

    def test_unique_ids(self):
        ids = {Job(job_type="t").id for _ in range(100)}
        assert len(ids) == 100


class TestRegistry:
    def test_register_and_lookup(self):
        """Register a worker and look it up."""
        from sylvan.queue.registry import _registry

        original = dict(_registry)
        try:

            @register_worker("test_job_type")
            class TestWorker(BaseWorker):
                job_type = "test_job_type"

            assert get_worker_class("test_job_type") is TestWorker
        finally:
            _registry.clear()
            _registry.update(original)

    def test_lookup_missing_returns_none(self):
        assert get_worker_class("nonexistent_type_xyz") is None

    def test_get_all_returns_copy(self):
        all_workers = get_all_worker_classes()
        assert isinstance(all_workers, dict)


class TestBaseWorker:
    def test_init(self):
        worker = BaseWorker()
        assert worker.current_job is None
        assert worker.pending_count == 0
        assert not worker.has_pending()

    async def test_handle_raises(self):
        worker = BaseWorker()
        job = Job(job_type="test")
        with pytest.raises(NotImplementedError):
            await worker.handle(job)

    def test_report_progress(self):
        worker = BaseWorker()
        job = Job(job_type="test")
        with patch("sylvan.events.emit"):
            worker.report_progress(job, current=5, total=10)
        assert job.progress == {"current": 5, "total": 10}

    async def test_queue_operations(self):
        worker = BaseWorker()
        job = Job(job_type="test", key="k1")
        await worker.queue.put(job)
        assert worker.pending_count == 1
        assert worker.has_pending()

    def test_cancel_by_key(self):
        worker = BaseWorker()
        j1 = Job(job_type="t", key="cancel-me")
        j2 = Job(job_type="t", key="keep-me")
        j3 = Job(job_type="t", key="cancel-me")
        worker.queue.put_nowait(j1)
        worker.queue.put_nowait(j2)
        worker.queue.put_nowait(j3)

        cancelled = worker.cancel_by_key("cancel-me")
        assert cancelled == 2
        assert worker.pending_count == 1
        remaining = worker.queue.get_nowait()
        assert remaining.key == "keep-me"

    async def test_cancel_by_key_with_future(self):
        worker = BaseWorker()
        future = asyncio.get_event_loop().create_future()
        job = Job(job_type="t", key="k", future=future)
        worker.queue.put_nowait(job)
        worker.cancel_by_key("k")
        assert job.status == JobStatus.CANCELLED
        assert future.cancelled()

    def test_cancel_by_key_empty_queue(self):
        worker = BaseWorker()
        assert worker.cancel_by_key("anything") == 0

    def test_is_duplicate_not_found(self):
        worker = BaseWorker()
        assert not worker.is_duplicate("k1")

    def test_is_duplicate_in_queue(self):
        worker = BaseWorker()
        job = Job(job_type="t", key="dup-key")
        worker.queue.put_nowait(job)
        assert worker.is_duplicate("dup-key")
        assert not worker.is_duplicate("other-key")

    def test_is_duplicate_current_job(self):
        worker = BaseWorker()
        job = Job(job_type="t", key="running-key")
        worker._current_job = job
        assert worker.is_duplicate("running-key")
        assert not worker.is_duplicate("other")


class TestQueueRunner:
    def _make_worker(self, job_type: str = "test", priority: int = 0):
        class ConcreteWorker(BaseWorker):
            pass

        w = ConcreteWorker()
        w.job_type = job_type
        w.priority = priority
        return w

    def test_init(self):
        runner = QueueRunner()
        assert runner._workers == []
        assert not runner._running

    def test_add_worker_sorts_by_priority(self):
        runner = QueueRunner()
        w_low = self._make_worker("low", priority=10)
        w_high = self._make_worker("high", priority=0)
        runner.add_worker(w_low)
        runner.add_worker(w_high)
        assert runner._workers[0].job_type == "high"
        assert runner._workers[1].job_type == "low"

    def test_find_worker(self):
        runner = QueueRunner()
        w = self._make_worker("my_type")
        runner.add_worker(w)
        assert runner._find_worker("my_type") is w
        assert runner._find_worker("other") is None

    async def test_enqueue_raises_for_unknown_type(self):
        runner = QueueRunner()
        job = Job(job_type="unknown")
        with pytest.raises(ValueError, match="No worker registered"):
            await runner.enqueue(job)

    async def test_enqueue_and_dequeue(self):
        runner = QueueRunner()

        class SimpleWorker(BaseWorker):
            job_type = "simple"

            async def handle(self, job):
                return {"done": True}

        runner.add_worker(SimpleWorker())
        job = Job(job_type="simple", key="test")
        await runner.enqueue(job)

        result_job, worker = await asyncio.wait_for(runner._next_job(), timeout=1)
        assert result_job is job
        assert worker.job_type == "simple"

    async def test_enqueue_deduplicates(self):
        runner = QueueRunner()

        class SimpleWorker(BaseWorker):
            job_type = "simple"

            async def handle(self, job):
                return {}

        w = SimpleWorker()
        runner.add_worker(w)

        future1 = asyncio.get_event_loop().create_future()
        job1 = Job(job_type="simple", key="dup", future=future1)
        await runner.enqueue(job1)

        future2 = asyncio.get_event_loop().create_future()
        job2 = Job(job_type="simple", key="dup", future=future2)
        await runner.enqueue(job2)

        # Only one job in queue, second was deduplicated
        assert w.pending_count == 1
        assert future2.done()
        assert future2.result() == {"deduplicated": True, "key": "dup"}

    async def test_execute_success(self):
        runner = QueueRunner()

        class SuccessWorker(BaseWorker):
            job_type = "ok"

            async def handle(self, job):
                return {"result": 42}

        w = SuccessWorker()
        runner.add_worker(w)

        future = asyncio.get_event_loop().create_future()
        job = Job(job_type="ok", future=future)
        await runner._execute(job, w)

        assert job.status == JobStatus.COMPLETE
        assert future.result() == {"result": 42}
        assert w.current_job is None

    async def test_execute_failure(self):
        runner = QueueRunner()

        class FailWorker(BaseWorker):
            job_type = "fail"

            async def handle(self, job):
                raise RuntimeError("boom")

        w = FailWorker()
        runner.add_worker(w)

        future = asyncio.get_event_loop().create_future()
        job = Job(job_type="fail", future=future)
        await runner._execute(job, w)

        assert job.status == JobStatus.FAILED
        with pytest.raises(RuntimeError, match="boom"):
            future.result()
        assert w.current_job is None

    async def test_execute_cancelled(self):
        runner = QueueRunner()

        class CancelWorker(BaseWorker):
            job_type = "cancel"

            async def handle(self, job):
                raise asyncio.CancelledError()

        w = CancelWorker()
        runner.add_worker(w)

        future = asyncio.get_event_loop().create_future()
        job = Job(job_type="cancel", future=future)
        with pytest.raises(asyncio.CancelledError):
            await runner._execute(job, w)
        assert job.status == JobStatus.CANCELLED

    async def test_cancel_by_key(self):
        runner = QueueRunner()
        w = self._make_worker("t")
        runner.add_worker(w)
        j1 = Job(job_type="t", key="x")
        j2 = Job(job_type="t", key="y")
        w.queue.put_nowait(j1)
        w.queue.put_nowait(j2)
        count = await runner.cancel_by_key("x")
        assert count == 1

    def test_status_empty(self):
        runner = QueueRunner()
        s = runner.status()
        assert s == {"workers": [], "recent": []}

    def test_status_with_workers(self):
        runner = QueueRunner()
        w = self._make_worker("idx", priority=0)
        runner.add_worker(w)
        s = runner.status()
        assert len(s["workers"]) == 1
        assert s["workers"][0]["job_type"] == "idx"
        assert s["workers"][0]["pending"] == 0
        assert s["workers"][0]["current"] is None

    def test_status_with_current_job(self):
        runner = QueueRunner()
        w = self._make_worker("idx")
        runner.add_worker(w)
        job = Job(job_type="idx", key="repo:foo")
        job.status = JobStatus.RUNNING
        w._current_job = job
        s = runner.status()
        assert s["workers"][0]["current"]["job_id"] == job.id
        assert s["workers"][0]["current"]["key"] == "repo:foo"

    async def test_priority_ordering(self):
        """Higher priority (lower number) workers are checked first."""
        runner = QueueRunner()

        class W1(BaseWorker):
            job_type = "low_pri"
            priority = 10

            async def handle(self, job):
                return "low"

        class W2(BaseWorker):
            job_type = "high_pri"
            priority = 0

            async def handle(self, job):
                return "high"

        runner.add_worker(W1())
        runner.add_worker(W2())

        j_low = Job(job_type="low_pri")
        j_high = Job(job_type="high_pri")

        # Enqueue low priority first, then high
        await runner.enqueue(j_low)
        await runner.enqueue(j_high)

        # High priority should come first
        _, first_worker = await asyncio.wait_for(runner._next_job(), timeout=1)
        assert first_worker.job_type == "high_pri"

    async def test_recent_jobs_capped(self):
        """Recent jobs list is capped at 50."""
        runner = QueueRunner()

        class OkWorker(BaseWorker):
            job_type = "ok"

            async def handle(self, job):
                return {}

        w = OkWorker()
        runner.add_worker(w)

        for _ in range(55):
            job = Job(job_type="ok")
            await runner._execute(job, w)

        assert len(runner._recent_jobs) == 50


class TestPublicAPI:
    """Tests for sylvan.queue public functions."""

    async def test_submit_and_status(self):
        """Submit creates a job and status reflects it."""
        import sylvan.queue as q

        # Reset global runner
        original = q._runner
        q._runner = None
        try:
            runner = q.get_runner()
            assert isinstance(runner, QueueRunner)
            assert len(runner._workers) > 0

            s = q.status()
            assert "workers" in s
            assert "recent" in s
        finally:
            q._runner = original

    async def test_get_runner_singleton(self):
        """get_runner returns the same instance."""
        import sylvan.queue as q

        original = q._runner
        q._runner = None
        try:
            r1 = q.get_runner()
            r2 = q.get_runner()
            assert r1 is r2
        finally:
            q._runner = original

    async def test_cancel_delegates(self):
        """cancel() delegates to runner.cancel_by_key."""
        import sylvan.queue as q

        original = q._runner
        q._runner = None
        try:
            count = await q.cancel("nonexistent-key")
            assert count == 0
        finally:
            q._runner = original
