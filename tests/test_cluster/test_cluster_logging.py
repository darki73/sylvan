"""Tests for sylvan.cluster.logging - log buffer and handler."""

from __future__ import annotations

import logging

from sylvan.cluster.logging import ClusterLogBuffer, ClusterLogHandler, get_buffer


class TestClusterLogBuffer:
    def test_append_and_len(self):
        buf = ClusterLogBuffer()
        assert len(buf) == 0
        buf.append({"event": "test"})
        assert len(buf) == 1

    def test_flush_returns_entries(self):
        buf = ClusterLogBuffer()
        buf.append({"event": "a"})
        buf.append({"event": "b"})
        entries = buf.flush()
        assert len(entries) == 2
        assert entries[0]["event"] == "a"
        assert entries[1]["event"] == "b"
        assert len(buf) == 0

    def test_flush_empty(self):
        buf = ClusterLogBuffer()
        assert buf.flush() == []

    def test_max_size_respected(self):
        buf = ClusterLogBuffer(max_size=3)
        for i in range(5):
            buf.append({"i": i})
        assert len(buf) == 3
        entries = buf.flush()
        assert entries[0]["i"] == 2
        assert entries[-1]["i"] == 4

    def test_multiple_flushes(self):
        buf = ClusterLogBuffer()
        buf.append({"x": 1})
        first = buf.flush()
        assert len(first) == 1
        buf.append({"x": 2})
        second = buf.flush()
        assert len(second) == 1
        assert second[0]["x"] == 2


class TestClusterLogHandler:
    def test_init(self):
        handler = ClusterLogHandler("node-1", "leader")
        assert handler.node_id == "node-1"
        assert handler.role == "leader"

    def test_emit_buffers_record(self):
        handler = ClusterLogHandler("node-2", "follower")
        buf = get_buffer()
        initial_len = len(buf)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        assert len(buf) > initial_len

        entries = buf.flush()
        matching = [e for e in entries if e.get("instance_id") == "node-2"]
        assert len(matching) >= 1
        entry = matching[-1]
        assert entry["level"] == "info"
        assert entry["role"] == "follower"
        assert entry["logger"] == "test.logger"

    def test_emit_with_structlog_event(self):
        handler = ClusterLogHandler("node-3", "leader")
        buf = get_buffer()

        record = logging.LogRecord(
            name="sylvan.test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="fallback",
            args=(),
            exc_info=None,
        )
        record.event = "custom_event_name"
        handler.emit(record)

        entries = buf.flush()
        matching = [e for e in entries if e.get("instance_id") == "node-3"]
        assert matching[-1]["event"] == "custom_event_name"
        assert matching[-1]["level"] == "warning"


class TestGetBuffer:
    def test_returns_buffer_instance(self):
        buf = get_buffer()
        assert isinstance(buf, ClusterLogBuffer)

    def test_returns_singleton(self):
        assert get_buffer() is get_buffer()
