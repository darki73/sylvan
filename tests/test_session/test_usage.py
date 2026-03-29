"""Tests for usage stats direct recording."""

import pytest

from sylvan.database.orm.models.usage_stats import UsageStats
from sylvan.session.usage_stats import record_usage


@pytest.fixture
async def usage_ctx(ctx):
    """Provide a context for usage tests."""
    return ctx


class TestRecordUsage:
    async def test_records_tool_call(self, usage_ctx):
        await record_usage(repo_id=1, tool_calls=1)
        row = await UsageStats.where(repo_id=1).first()
        assert row is not None
        assert row.tool_calls == 1

    async def test_accumulates_on_same_day(self, usage_ctx):
        await record_usage(repo_id=1, tool_calls=1, tokens_returned=100)
        await record_usage(repo_id=1, tool_calls=1, tokens_returned=200)
        row = await UsageStats.where(repo_id=1).first()
        assert row.tool_calls == 2
        assert row.tokens_returned == 300

    async def test_tracks_global_calls(self, usage_ctx):
        await record_usage(repo_id=0, tool_calls=1)
        row = await UsageStats.where(repo_id=0).first()
        assert row is not None
        assert row.tool_calls == 1

    async def test_tracks_efficiency_by_category(self, usage_ctx):
        await record_usage(
            repo_id=1,
            tool_calls=1,
            tokens_returned_search=100,
            tokens_equivalent_search=500,
        )
        row = await UsageStats.where(repo_id=1).first()
        assert row.tokens_returned_search == 100
        assert row.tokens_equivalent_search == 500

    async def test_separate_repos_separate_rows(self, usage_ctx):
        await record_usage(repo_id=1, tool_calls=1)
        await record_usage(repo_id=2, tool_calls=1)
        count = await UsageStats.all().count()
        assert count == 2
