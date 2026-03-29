"""Extended tests for usage stats - aggregation queries."""

from __future__ import annotations

import pytest

from sylvan.session.usage_stats import async_get_overall_usage, async_get_project_usage, record_usage


@pytest.fixture
async def usage_ctx(ctx):
    """Provide a context for usage tests."""
    return ctx


class TestAsyncGetProjectUsage:
    async def test_returns_aggregated_stats(self, usage_ctx):
        await record_usage(repo_id=1, tool_calls=3, tokens_returned=100, tokens_avoided=400)
        await record_usage(repo_id=1, tool_calls=2, tokens_returned=50, tokens_avoided=200)

        from sylvan.database.orm.runtime.connection_manager import get_backend

        stats = await async_get_project_usage(get_backend(), 1)
        assert stats["total_tool_calls"] == 5
        assert stats["total_tokens_returned"] == 150
        assert stats["total_tokens_avoided"] == 600

    async def test_empty_repo(self, usage_ctx):
        from sylvan.database.orm.runtime.connection_manager import get_backend

        stats = await async_get_project_usage(get_backend(), 999)
        assert stats["total_tool_calls"] == 0 or stats["total_tool_calls"] is None


class TestAsyncGetOverallUsage:
    async def test_aggregates_across_repos(self, usage_ctx):
        await record_usage(repo_id=1, tool_calls=3)
        await record_usage(repo_id=2, tool_calls=5)

        from sylvan.database.orm.runtime.connection_manager import get_backend

        stats = await async_get_overall_usage(get_backend())
        assert stats["total_tool_calls"] == 8
        assert stats["repos_used"] == 2
