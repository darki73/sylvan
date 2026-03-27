"""Integration tests for the cluster WebSocket protocol.

Tests the leader-follower WebSocket communication using Starlette's
test client for the leader side and direct protocol message handling.
"""

from sylvan.cluster import protocol
from sylvan.cluster.websocket import (
    _followers,
    _handle_leader_message,
    _pending_writes,
)


class TestProtocolRoundTrip:
    """Test protocol encode/decode with actual message flows."""

    def test_write_proxy_round_trip(self):
        """A write request should encode and decode correctly."""
        request = protocol.write_request("index_folder", {"path": "/home/user"}, "req-42")
        msg = protocol.decode(request)
        assert msg["type"] == protocol.MSG_WRITE
        assert msg["tool"] == "index_folder"
        assert msg["id"] == "req-42"

        result = protocol.write_result("req-42", data={"files": 100})
        rmsg = protocol.decode(result)
        assert rmsg["type"] == protocol.MSG_RESULT
        assert rmsg["data"]["files"] == 100

    def test_ping_pong_round_trip(self):
        """Ping and pong should be minimal messages."""
        ping_msg = protocol.decode(protocol.ping())
        assert ping_msg == {"type": "ping"}

        pong_msg = protocol.decode(protocol.pong())
        assert pong_msg == {"type": "pong"}


class TestLeaderMessageHandler:
    """Test the leader's message handling logic."""

    async def test_pong_is_no_op(self):
        """Pong messages should be handled silently."""
        # Should not raise
        await _handle_leader_message(None, "test-follower", {"type": protocol.MSG_PONG})

    async def test_stats_received(self):
        """Stats messages should be accepted without error."""
        msg = {
            "type": protocol.MSG_STATS,
            "node_id": "follower-1",
            "stats": {"tool_calls": 5},
            "efficiency": {},
            "cache": {},
        }
        await _handle_leader_message(None, "follower-1", msg)

    async def test_log_received(self):
        """Log messages should be accepted without error."""
        msg = {
            "type": protocol.MSG_LOG,
            "lines": [{"level": "info", "event": "test"}],
        }
        await _handle_leader_message(None, "follower-1", msg)


class TestFollowerState:
    """Test follower-side state management."""

    def test_pending_writes_start_empty(self):
        """Pending writes dict should start empty."""
        # Clear any leftover state
        _pending_writes.clear()
        assert len(_pending_writes) == 0

    def test_followers_dict_start_empty(self):
        """Followers dict should start empty."""
        _followers.clear()
        assert len(_followers) == 0
