"""Tests for sylvan.session.usage_stats - usage recording and querying."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

from sylvan.database.orm import Repo, UsageStats


class TestRecordUsage:
    async def test_leader_writes_to_db(self, ctx):
        """Leader writes usage directly to the database."""
        from sylvan.session.usage_stats import record_usage

        now = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        repo = await Repo.create(name="usage-repo", source_path="/u", repo_type="local", indexed_at=now)

        with patch("sylvan.cluster.state.get_cluster_state") as mock_state:
            mock_state.return_value.is_follower = False
            await record_usage(
                repo_id=repo.id,
                tool_calls=3,
                tokens_returned=100,
                tokens_avoided=200,
                symbols_retrieved=5,
            )

        rows = await UsageStats.where(repo_id=repo.id).get()
        assert len(rows) == 1
        assert rows[0].tool_calls == 3
        assert rows[0].tokens_returned == 100
        assert rows[0].tokens_avoided == 200
        assert rows[0].symbols_retrieved == 5

    async def test_upsert_increments(self, ctx):
        """Multiple calls for the same repo_id + date increment counters."""
        from sylvan.session.usage_stats import record_usage

        now = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        repo = await Repo.create(name="upsert-repo", source_path="/up", repo_type="local", indexed_at=now)

        with patch("sylvan.cluster.state.get_cluster_state") as mock_state:
            mock_state.return_value.is_follower = False
            await record_usage(repo_id=repo.id, tool_calls=1, tokens_returned=50)
            await record_usage(repo_id=repo.id, tool_calls=2, tokens_returned=30)

        rows = await UsageStats.where(repo_id=repo.id).get()
        assert len(rows) == 1
        assert rows[0].tool_calls == 3
        assert rows[0].tokens_returned == 80

    async def test_follower_relays(self, ctx):
        """Follower calls _relay_to_leader instead of _write_to_db."""
        import contextlib

        from sylvan.session.usage_stats import record_usage

        with patch("sylvan.cluster.state.get_cluster_state") as mock_state:
            mock_state.return_value.is_follower = True
            # Relay may fail without a real leader connection
            with contextlib.suppress(Exception):
                await record_usage(repo_id=1, tool_calls=1)
            rows = await UsageStats.where(repo_id=1).get()
            assert len(rows) == 0  # follower should not write to local DB


class TestFlushAll:
    def test_flush_all_is_noop(self):
        from sylvan.session.usage_stats import flush_all

        flush_all()  # should not raise


class TestAsyncGetProjectUsage:
    async def test_empty_returns_zeroes(self, ctx):
        from sylvan.session.usage_stats import async_get_project_usage

        result = await async_get_project_usage(ctx.backend, 999)
        assert result["total_tool_calls"] == 0
        assert result["days_active"] == 0

    async def test_returns_aggregated_data(self, ctx):
        from sylvan.session.usage_stats import async_get_project_usage, record_usage

        now = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        repo = await Repo.create(name="proj-usage", source_path="/pu", repo_type="local", indexed_at=now)

        with patch("sylvan.cluster.state.get_cluster_state") as mock_state:
            mock_state.return_value.is_follower = False
            await record_usage(repo_id=repo.id, tool_calls=5, symbols_retrieved=10)

        result = await async_get_project_usage(ctx.backend, repo.id)
        assert result["total_tool_calls"] == 5
        assert result["total_symbols_retrieved"] == 10
        assert result["days_active"] == 1


class TestAsyncGetOverallUsage:
    async def test_empty_returns_zeroes(self, ctx):
        from sylvan.session.usage_stats import async_get_overall_usage

        result = await async_get_overall_usage(ctx.backend)
        assert result["total_tool_calls"] == 0
        assert result["repos_used"] == 0

    async def test_aggregates_across_repos(self, ctx):
        from sylvan.session.usage_stats import async_get_overall_usage, record_usage

        now = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        r1 = await Repo.create(name="overall-1", source_path="/o1", repo_type="local", indexed_at=now)
        r2 = await Repo.create(name="overall-2", source_path="/o2", repo_type="local", indexed_at=now)

        with patch("sylvan.cluster.state.get_cluster_state") as mock_state:
            mock_state.return_value.is_follower = False
            await record_usage(repo_id=r1.id, tool_calls=3)
            await record_usage(repo_id=r2.id, tool_calls=7)

        result = await async_get_overall_usage(ctx.backend)
        assert result["total_tool_calls"] == 10
        assert result["repos_used"] == 2


class TestSyncUsageFunctions:
    def test_get_project_usage_empty(self, tmp_path):
        from sylvan.session.usage_stats import get_project_usage

        db = tmp_path / "sync_test.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE usage_stats (
            repo_id INTEGER, date TEXT, tool_calls INTEGER DEFAULT 0,
            tokens_returned INTEGER DEFAULT 0, tokens_avoided INTEGER DEFAULT 0,
            symbols_retrieved INTEGER DEFAULT 0, sections_retrieved INTEGER DEFAULT 0,
            tokens_returned_search INTEGER DEFAULT 0, tokens_equivalent_search INTEGER DEFAULT 0,
            tokens_returned_retrieval INTEGER DEFAULT 0, tokens_equivalent_retrieval INTEGER DEFAULT 0,
            sessions INTEGER DEFAULT 0,
            PRIMARY KEY (repo_id, date))""")
        result = get_project_usage(conn, 1)
        assert result["total_tool_calls"] == 0
        assert result["days_active"] == 0
        conn.close()

    def test_get_project_usage_with_data(self, tmp_path):
        from sylvan.session.usage_stats import get_project_usage

        db = tmp_path / "sync_test2.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE usage_stats (
            repo_id INTEGER, date TEXT, tool_calls INTEGER DEFAULT 0,
            tokens_returned INTEGER DEFAULT 0, tokens_avoided INTEGER DEFAULT 0,
            symbols_retrieved INTEGER DEFAULT 0, sections_retrieved INTEGER DEFAULT 0,
            tokens_returned_search INTEGER DEFAULT 0, tokens_equivalent_search INTEGER DEFAULT 0,
            tokens_returned_retrieval INTEGER DEFAULT 0, tokens_equivalent_retrieval INTEGER DEFAULT 0,
            sessions INTEGER DEFAULT 0,
            PRIMARY KEY (repo_id, date))""")
        conn.execute(
            "INSERT INTO usage_stats (repo_id, date, tool_calls, symbols_retrieved) VALUES (1, '2026-03-29', 10, 5)"
        )
        conn.commit()
        result = get_project_usage(conn, 1)
        assert result["total_tool_calls"] == 10
        assert result["total_symbols_retrieved"] == 5
        assert result["days_active"] == 1
        conn.close()

    def test_get_overall_usage_empty(self, tmp_path):
        from sylvan.session.usage_stats import get_overall_usage

        db = tmp_path / "sync_test3.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE usage_stats (
            repo_id INTEGER, date TEXT, tool_calls INTEGER DEFAULT 0,
            tokens_returned INTEGER DEFAULT 0, tokens_avoided INTEGER DEFAULT 0,
            symbols_retrieved INTEGER DEFAULT 0, sections_retrieved INTEGER DEFAULT 0,
            tokens_returned_search INTEGER DEFAULT 0, tokens_equivalent_search INTEGER DEFAULT 0,
            tokens_returned_retrieval INTEGER DEFAULT 0, tokens_equivalent_retrieval INTEGER DEFAULT 0,
            sessions INTEGER DEFAULT 0,
            PRIMARY KEY (repo_id, date))""")
        result = get_overall_usage(conn)
        assert result["total_tool_calls"] == 0
        assert result["repos_used"] == 0
        conn.close()

    def test_get_overall_usage_with_data(self, tmp_path):
        from sylvan.session.usage_stats import get_overall_usage

        db = tmp_path / "sync_test4.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE usage_stats (
            repo_id INTEGER, date TEXT, tool_calls INTEGER DEFAULT 0,
            tokens_returned INTEGER DEFAULT 0, tokens_avoided INTEGER DEFAULT 0,
            symbols_retrieved INTEGER DEFAULT 0, sections_retrieved INTEGER DEFAULT 0,
            tokens_returned_search INTEGER DEFAULT 0, tokens_equivalent_search INTEGER DEFAULT 0,
            tokens_returned_retrieval INTEGER DEFAULT 0, tokens_equivalent_retrieval INTEGER DEFAULT 0,
            sessions INTEGER DEFAULT 0,
            PRIMARY KEY (repo_id, date))""")
        conn.execute("INSERT INTO usage_stats (repo_id, date, tool_calls) VALUES (1, '2026-03-29', 5)")
        conn.execute("INSERT INTO usage_stats (repo_id, date, tool_calls) VALUES (2, '2026-03-29', 3)")
        conn.commit()
        result = get_overall_usage(conn)
        assert result["total_tool_calls"] == 8
        assert result["repos_used"] == 2
        conn.close()
