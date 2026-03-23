"""Extended tests for sylvan.session.usage_stats — async flush, retry, edge cases."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker
from sylvan.session.usage_stats import UsageAccumulator, flush_all, get_accumulator


@pytest.fixture
async def usage_ctx(tmp_path):
    """Create backend + context for usage tests."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    reset_config()

    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(ctx)

    yield ctx

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)
    reset_config()


class TestUsageAccumulatorAsyncFlush:
    async def test_flush_empty_is_noop(self, usage_ctx):
        acc = UsageAccumulator()
        await acc.async_flush()
        assert len(acc._pending) == 0

    async def test_flush_clears_pending(self, usage_ctx):
        acc = UsageAccumulator()
        acc.increment(1, tool_calls=5, tokens_returned=100)
        acc.increment(2, tool_calls=3, tokens_returned=50)

        await acc.async_flush()

        assert len(acc._pending) == 0
        assert acc._call_count == 0

    async def test_flush_writes_to_db(self, usage_ctx):
        # First create a repo so FK constraint is met
        backend = usage_ctx.backend
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["test-repo", "/test/repo"],
        )
        await backend.commit()

        acc = UsageAccumulator()
        acc.increment(1, tool_calls=3, tokens_returned=100, tokens_avoided=200)

        await acc.async_flush()

        row = await backend.fetch_one(
            "SELECT * FROM usage_stats WHERE repo_id = ?", [1]
        )
        assert row is not None
        assert row["tool_calls"] == 3
        assert row["tokens_returned"] == 100
        assert row["tokens_avoided"] == 200

    async def test_flush_accumulates_on_conflict(self, usage_ctx):
        """Two flushes on the same day should accumulate values."""
        backend = usage_ctx.backend
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["test-repo", "/test/repo"],
        )
        await backend.commit()

        acc = UsageAccumulator()
        acc.increment(1, tool_calls=2, tokens_returned=100)
        await acc.async_flush()

        acc.increment(1, tool_calls=3, tokens_returned=200)
        await acc.async_flush()

        row = await backend.fetch_one(
            "SELECT * FROM usage_stats WHERE repo_id = ?", [1]
        )
        assert row["tool_calls"] == 5
        assert row["tokens_returned"] == 300

    async def test_async_flush_fallback_on_error(self):
        """When async backend raises, pending data is re-enqueued for sync flush."""
        acc = UsageAccumulator()
        acc.increment(1, tool_calls=1)

        # Mock get_context to raise
        with patch("sylvan.session.usage_stats.get_connection", side_effect=Exception("no db")), patch("sylvan.context.get_context", side_effect=Exception("no context")):
            await acc.async_flush()

        # After failed flush, pending should be cleared (sync flush also failed)
        # but the code handles this gracefully
        assert acc._call_count == 0


class TestUsageAccumulatorIncrement:
    def test_increment_creates_entry(self):
        acc = UsageAccumulator()
        acc.increment(42, tool_calls=1, tokens_returned=100)

        assert 42 in acc._pending
        assert acc._pending[42]["tool_calls"] == 1
        assert acc._pending[42]["tokens_returned"] == 100

    def test_increment_accumulates(self):
        acc = UsageAccumulator()
        acc.increment(1, tool_calls=1, symbols_retrieved=5)
        acc.increment(1, tool_calls=2, symbols_retrieved=3)

        assert acc._pending[1]["tool_calls"] == 3
        assert acc._pending[1]["symbols_retrieved"] == 8

    def test_increment_multiple_repos(self):
        acc = UsageAccumulator()
        acc.increment(1, tool_calls=1)
        acc.increment(2, tool_calls=2)

        assert acc._pending[1]["tool_calls"] == 1
        assert acc._pending[2]["tool_calls"] == 2
        assert acc._call_count == 2

    def test_defaults_to_zero(self):
        acc = UsageAccumulator()
        acc.increment(1)

        p = acc._pending[1]
        assert p["tool_calls"] == 0
        assert p["tokens_returned"] == 0
        assert p["tokens_avoided"] == 0
        assert p["symbols_retrieved"] == 0
        assert p["sections_retrieved"] == 0


class TestFlushAll:
    def test_noop_when_no_accumulator(self):
        import sylvan.session.usage_stats as mod
        old = mod._accumulator
        mod._accumulator = None
        flush_all()  # Should not raise
        mod._accumulator = old

    def test_flush_all_suppresses_errors(self):
        import sylvan.session.usage_stats as mod
        old = mod._accumulator

        acc = UsageAccumulator()
        acc.increment(1, tool_calls=1)
        # Make flush raise by patching get_connection
        mod._accumulator = acc
        with patch("sylvan.session.usage_stats.get_connection", side_effect=Exception("fail")):
            flush_all()  # Should not raise

        mod._accumulator = old


class TestGetAccumulator:
    def test_returns_singleton(self):
        import sylvan.session.usage_stats as mod
        old = mod._accumulator
        mod._accumulator = None

        a1 = get_accumulator()
        a2 = get_accumulator()
        assert a1 is a2

        mod._accumulator = old


class TestSyncFlush:
    def test_flush_clears_pending(self):
        acc = UsageAccumulator()
        acc.increment(1, tool_calls=1)

        # Mock get_connection to avoid real DB
        mock_conn = MagicMock()
        with patch("sylvan.session.usage_stats.get_connection", return_value=mock_conn):
            acc.flush()

        assert len(acc._pending) == 0
        assert acc._call_count == 0

    def test_flush_empty_is_noop(self):
        acc = UsageAccumulator()
        acc.flush()  # Should not raise, no DB call needed
        assert len(acc._pending) == 0

    def test_flush_handles_db_error(self):
        acc = UsageAccumulator()
        acc.increment(1, tool_calls=1)

        with patch("sylvan.session.usage_stats.get_connection", side_effect=Exception("db error")):
            acc.flush()  # Should not raise

        # Pending should be cleared even on error
        assert len(acc._pending) == 0
