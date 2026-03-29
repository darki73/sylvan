"""Tests for sylvan.events - event bus with sync/async handlers and queues."""

from __future__ import annotations

import asyncio

from sylvan.events import create_queue, emit, off, on, remove_queue


class TestOn:
    def test_registers_sync_handler(self):
        from sylvan.events import _sync_listeners

        def handler(data):
            pass

        on("test_sync", handler)
        assert handler in _sync_listeners["test_sync"]
        off("test_sync", handler)

    def test_registers_async_handler(self):
        from sylvan.events import _async_listeners

        async def handler(data):
            pass

        on("test_async", handler)
        assert handler in _async_listeners["test_async"]
        off("test_async", handler)


class TestOff:
    def test_removes_sync_handler(self):
        from sylvan.events import _sync_listeners

        def handler(data):
            pass

        on("test_off_sync", handler)
        off("test_off_sync", handler)
        assert handler not in _sync_listeners["test_off_sync"]

    def test_removes_async_handler(self):
        from sylvan.events import _async_listeners

        async def handler(data):
            pass

        on("test_off_async", handler)
        off("test_off_async", handler)
        assert handler not in _async_listeners["test_off_async"]

    def test_off_nonexistent_handler_no_error(self):
        def handler(data):
            pass

        off("never_registered_event", handler)


class TestEmit:
    def test_calls_sync_handler(self):
        received = []

        def handler(data):
            received.append(data)

        on("emit_sync", handler)
        try:
            emit("emit_sync", {"key": "value"})
            assert len(received) == 1
            assert received[0] == {"key": "value"}
        finally:
            off("emit_sync", handler)

    def test_sync_handler_exception_swallowed(self):
        def bad_handler(data):
            raise ValueError("boom")

        on("emit_err", bad_handler)
        try:
            emit("emit_err", "data")  # should not raise
        finally:
            off("emit_err", bad_handler)

    async def test_calls_async_handler(self):
        received = []

        async def handler(data):
            received.append(data)

        on("emit_async", handler)
        try:
            emit("emit_async", {"async": True})
            await asyncio.sleep(0.05)  # let the task run
            assert len(received) == 1
            assert received[0] == {"async": True}
        finally:
            off("emit_async", handler)

    def test_emits_to_queues(self):
        q = create_queue()
        try:
            emit("queue_event", {"q": 1})
            msg = q.get_nowait()
            assert msg["type"] == "queue_event"
            assert msg["data"] == {"q": 1}
        finally:
            remove_queue(q)

    def test_full_queue_is_discarded(self):
        q = create_queue(maxsize=1)
        try:
            emit("fill_1", "a")
            emit("fill_2", "b")  # queue is full, should not raise
            msg = q.get_nowait()
            assert msg["type"] == "fill_1"
            assert q.empty()  # second event was dropped, queue was removed
        finally:
            remove_queue(q)

    def test_emit_no_listeners_no_error(self):
        emit("no_listeners_event", None)

    def test_emit_none_data(self):
        received = []

        def handler(data):
            received.append(data)

        on("emit_none", handler)
        try:
            emit("emit_none")
            assert received == [None]
        finally:
            off("emit_none", handler)


class TestQueue:
    def test_create_and_remove(self):
        from sylvan.events import _queues

        q = create_queue()
        assert q in _queues
        remove_queue(q)
        assert q not in _queues

    def test_remove_nonexistent_no_error(self):
        q = asyncio.Queue()
        remove_queue(q)  # should not raise

    def test_custom_maxsize(self):
        q = create_queue(maxsize=10)
        try:
            assert q.maxsize == 10
        finally:
            remove_queue(q)

    def test_multiple_queues_receive(self):
        q1 = create_queue()
        q2 = create_queue()
        try:
            emit("multi_q", "hello")
            assert q1.get_nowait()["data"] == "hello"
            assert q2.get_nowait()["data"] == "hello"
        finally:
            remove_queue(q1)
            remove_queue(q2)
