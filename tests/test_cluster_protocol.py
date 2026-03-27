"""Tests for the cluster WebSocket protocol."""

from sylvan.cluster.protocol import (
    MSG_LOG,
    MSG_PING,
    MSG_PONG,
    MSG_RESULT,
    MSG_STATS,
    MSG_STEP_DOWN,
    MSG_WRITE,
    decode,
    encode,
    log_message,
    ping,
    pong,
    stats_message,
    step_down,
    write_request,
    write_result,
)


class TestEncodeDecode:
    def test_round_trip(self):
        """Encode then decode should return the same data."""
        data = {"type": "test", "value": 42, "nested": {"a": [1, 2]}}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_encode_is_compact(self):
        """Encoded JSON should have no extra whitespace."""
        result = encode({"a": 1, "b": 2})
        assert " " not in result


class TestPingPong:
    def test_ping_message(self):
        msg = decode(ping())
        assert msg["type"] == MSG_PING

    def test_pong_message(self):
        msg = decode(pong())
        assert msg["type"] == MSG_PONG


class TestStepDown:
    def test_step_down_without_new_leader(self):
        msg = decode(step_down())
        assert msg["type"] == MSG_STEP_DOWN
        assert "new_leader" not in msg

    def test_step_down_with_new_leader(self):
        msg = decode(step_down("node-2"))
        assert msg["type"] == MSG_STEP_DOWN
        assert msg["new_leader"] == "node-2"


class TestWriteProxy:
    def test_write_request(self):
        msg = decode(write_request("index_folder", {"path": "/home/user/project"}, "req-1"))
        assert msg["type"] == MSG_WRITE
        assert msg["id"] == "req-1"
        assert msg["tool"] == "index_folder"
        assert msg["args"]["path"] == "/home/user/project"

    def test_write_request_auto_id(self):
        msg = decode(write_request("index_folder", {}))
        assert msg["type"] == MSG_WRITE
        assert len(msg["id"]) == 8

    def test_write_result_success(self):
        msg = decode(write_result("req-1", data={"files": 10}))
        assert msg["type"] == MSG_RESULT
        assert msg["id"] == "req-1"
        assert msg["data"]["files"] == 10
        assert "error" not in msg

    def test_write_result_error(self):
        msg = decode(write_result("req-1", error="not found"))
        assert msg["type"] == MSG_RESULT
        assert msg["id"] == "req-1"
        assert msg["error"] == "not found"


class TestStats:
    def test_stats_message(self):
        msg = decode(
            stats_message(
                "node-1",
                {"tool_calls": 5},
                {"total_returned": 100},
                {"hits": 3, "misses": 1},
            )
        )
        assert msg["type"] == MSG_STATS
        assert msg["node_id"] == "node-1"
        assert msg["stats"]["tool_calls"] == 5


class TestLog:
    def test_log_message(self):
        lines = [
            {"timestamp": "2026-01-01", "level": "info", "event": "test"},
            {"timestamp": "2026-01-01", "level": "debug", "event": "other"},
        ]
        msg = decode(log_message(lines))
        assert msg["type"] == MSG_LOG
        assert len(msg["lines"]) == 2

    def test_log_message_empty(self):
        msg = decode(log_message([]))
        assert msg["type"] == MSG_LOG
        assert msg["lines"] == []
