"""Tests for cluster ORM models: ClusterLock, ClusterNode, Instance."""

from sylvan.database.orm import ClusterLock, ClusterNode, Instance


class TestClusterLock:
    async def test_claim_succeeds_on_empty_lock(self, ctx):
        """Claiming an unclaimed lock should succeed."""
        result = await ClusterLock.claim("node-1", 12345)
        assert result is True

    async def test_claim_fails_when_already_held(self, ctx):
        """Second claim should fail while first holder is active."""
        await ClusterLock.claim("node-1", 12345)
        result = await ClusterLock.claim("node-2", 67890, stale_seconds=9999)
        assert result is False

    async def test_claim_succeeds_on_stale_lock(self, ctx):
        """Claiming a stale lock (very old heartbeat) should succeed."""
        await ClusterLock.claim("node-1", 12345)
        # Force heartbeat to be very old
        await ClusterLock.where(holder_id="node-1").update(heartbeat_at="2020-01-01T00:00:00")
        await ctx.backend.commit()
        result = await ClusterLock.claim("node-2", 67890, stale_seconds=1)
        assert result is True

    async def test_release_clears_all_fields(self, ctx):
        """Release should set all fields to NULL."""
        await ClusterLock.claim("node-1", 12345)
        await ClusterLock.release()
        await ctx.backend.commit()
        holder = await ClusterLock.holder()
        assert holder is None

    async def test_refresh_updates_heartbeat(self, ctx):
        """Refresh should update the heartbeat_at timestamp."""
        await ClusterLock.claim("node-1", 12345)
        await ctx.backend.commit()
        lock_before = await ClusterLock.holder()
        old_heartbeat = lock_before.heartbeat_at

        await ClusterLock.refresh("node-1")
        await ctx.backend.commit()
        lock_after = await ClusterLock.holder()
        assert lock_after.heartbeat_at >= old_heartbeat

    async def test_holder_returns_none_when_empty(self, ctx):
        """Holder should return None when lock is unclaimed."""
        holder = await ClusterLock.holder()
        assert holder is None

    async def test_holder_returns_lock_when_claimed(self, ctx):
        """Holder should return the lock row when claimed."""
        await ClusterLock.claim("node-1", 12345)
        await ctx.backend.commit()
        holder = await ClusterLock.holder()
        assert holder is not None
        assert holder.holder_id == "node-1"
        assert holder.pid == 12345


class TestClusterNode:
    async def test_create_node(self, ctx):
        """Creating a cluster node should persist all fields."""
        node = await ClusterNode.create(
            node_id="abc123",
            pid=9999,
            role="leader",
            ws_port=32400,
            connected_at="2026-01-01T00:00:00",
            last_seen="2026-01-01T00:00:00",
            coding_session_id="cs-test",
        )
        assert node.node_id == "abc123"
        assert node.role == "leader"

    async def test_leader_scope(self, ctx):
        """Leader scope should return only leader nodes."""
        await ClusterNode.create(
            node_id="n1", pid=1, role="leader", connected_at="x", last_seen="x", coding_session_id="cs"
        )
        await ClusterNode.create(
            node_id="n2", pid=2, role="follower", connected_at="x", last_seen="x", coding_session_id="cs"
        )
        await ctx.backend.commit()
        leaders = await ClusterNode.leader().get()
        assert len(leaders) == 1
        assert leaders[0].node_id == "n1"

    async def test_followers_scope(self, ctx):
        """Followers scope should return only follower nodes."""
        await ClusterNode.create(
            node_id="n1", pid=1, role="leader", connected_at="x", last_seen="x", coding_session_id="cs"
        )
        await ClusterNode.create(
            node_id="n2", pid=2, role="follower", connected_at="x", last_seen="x", coding_session_id="cs"
        )
        await ctx.backend.commit()
        followers = await ClusterNode.followers().get()
        assert len(followers) == 1
        assert followers[0].node_id == "n2"


class TestInstanceRevised:
    async def test_active_scope(self, ctx):
        """Active scope should return only instances without ended_at."""
        await ClusterNode.create(
            node_id="n1", pid=1, role="leader", connected_at="x", last_seen="x", coding_session_id="cs"
        )
        await Instance.create(instance_id="i1", node_id="n1", coding_session_id="cs", started_at="x")
        await Instance.create(instance_id="i2", node_id="n1", coding_session_id="cs", started_at="x", ended_at="y")
        await ctx.backend.commit()
        active = await Instance.active().get()
        assert len(active) == 1
        assert active[0].instance_id == "i1"

    async def test_reduction_percent_with_data(self, ctx):
        """reduction_percent should compute correctly."""
        await ClusterNode.create(
            node_id="n1", pid=1, role="leader", connected_at="x", last_seen="x", coding_session_id="cs"
        )
        inst = await Instance.create(
            instance_id="i1",
            node_id="n1",
            coding_session_id="cs",
            started_at="x",
            efficiency_returned=200,
            efficiency_equivalent=1000,
        )
        assert inst.reduction_percent == 80.0

    async def test_reduction_percent_zero_equivalent(self, ctx):
        """reduction_percent should return 0 when equivalent is 0."""
        await ClusterNode.create(
            node_id="n1", pid=1, role="leader", connected_at="x", last_seen="x", coding_session_id="cs"
        )
        inst = await Instance.create(
            instance_id="i1",
            node_id="n1",
            coding_session_id="cs",
            started_at="x",
            efficiency_returned=0,
            efficiency_equivalent=0,
        )
        assert inst.reduction_percent == 0.0
