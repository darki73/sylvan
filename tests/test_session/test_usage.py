"""Tests for sylvan.session.usage_stats — usage tracking and accumulation."""

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


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


class TestUsageAccumulator:
    async def test_increment_and_flush(self, usage_ctx):
        proj = usage_ctx.backend.db_path.parent / "project"
        proj.mkdir()
        (proj / "main.py").write_text("def foo(): pass\n")

        from sylvan.indexing.pipeline.orchestrator import index_folder
        result = await index_folder(str(proj), name="acc-test")
        await usage_ctx.backend.commit()
        repo_id = result.repo_id

        from sylvan.session.usage_stats import UsageAccumulator
        acc = UsageAccumulator()
        acc.increment(repo_id, tool_calls=1, tokens_returned=100, tokens_avoided=400)
        acc.increment(repo_id, tool_calls=1, tokens_returned=50, tokens_avoided=200)

        assert repo_id in acc._pending
        assert acc._pending[repo_id]["tool_calls"] == 2
        assert acc._pending[repo_id]["tokens_returned"] == 150
        assert acc._pending[repo_id]["tokens_avoided"] == 600

        await acc.async_flush()

        assert len(acc._pending) == 0
        assert acc._call_count == 0

        row = await usage_ctx.backend.fetch_one(
            "SELECT * FROM usage_stats WHERE repo_id = ?", [repo_id]
        )
        assert row is not None
        assert row["tool_calls"] == 2
        assert row["tokens_returned"] == 150
        assert row["tokens_avoided"] == 600

    async def test_accumulates_without_auto_flush(self, usage_ctx):
        """Increments accumulate in memory until explicit flush."""
        from sylvan.session.usage_stats import UsageAccumulator
        acc = UsageAccumulator()

        for _ in range(10):
            acc.increment(1, tool_calls=1)

        assert acc._call_count == 10
        assert acc._pending[1]["tool_calls"] == 10

    async def test_multiple_repos(self, usage_ctx):
        proj_a = usage_ctx.backend.db_path.parent / "proj_a"
        proj_a.mkdir()
        (proj_a / "a.py").write_text("def a(): pass\n")

        proj_b = usage_ctx.backend.db_path.parent / "proj_b"
        proj_b.mkdir()
        (proj_b / "b.py").write_text("def b(): pass\n")

        from sylvan.indexing.pipeline.orchestrator import index_folder
        r_a = await index_folder(str(proj_a), name="repo-a")
        r_b = await index_folder(str(proj_b), name="repo-b")
        await usage_ctx.backend.commit()

        from sylvan.session.usage_stats import UsageAccumulator
        acc = UsageAccumulator()
        acc.increment(r_a.repo_id, tool_calls=1, symbols_retrieved=3)
        acc.increment(r_b.repo_id, tool_calls=2, sections_retrieved=5)
        await acc.async_flush()

        assert len(acc._pending) == 0

        row_a = await usage_ctx.backend.fetch_one(
            "SELECT * FROM usage_stats WHERE repo_id = ?", [r_a.repo_id]
        )
        row_b = await usage_ctx.backend.fetch_one(
            "SELECT * FROM usage_stats WHERE repo_id = ?", [r_b.repo_id]
        )
        assert row_a["symbols_retrieved"] == 3
        assert row_b["sections_retrieved"] == 5


class TestRecordUsage:
    async def test_batching(self, usage_ctx):
        proj = usage_ctx.backend.db_path.parent / "project"
        proj.mkdir()
        (proj / "main.py").write_text("def x(): pass\n")

        from sylvan.indexing.pipeline.orchestrator import index_folder
        result = await index_folder(str(proj), name="record-test")
        await usage_ctx.backend.commit()
        repo_id = result.repo_id

        import sylvan.session.usage_stats as usage_mod
        usage_mod._accumulator = None

        from sylvan.session.usage_stats import async_flush_usage, record_usage
        record_usage(repo_id=repo_id, tokens_returned=100, tokens_avoided=500)
        record_usage(repo_id=repo_id, tokens_returned=200, tokens_avoided=300)
        await async_flush_usage()

        row = await usage_ctx.backend.fetch_one(
            "SELECT * FROM usage_stats WHERE repo_id = ?", [repo_id]
        )
        assert row is not None
        assert row["tool_calls"] == 2
        assert row["tokens_returned"] == 300
        assert row["tokens_avoided"] == 800


class TestGetProjectUsage:
    async def test_returns_correct_totals(self, usage_ctx):
        proj = usage_ctx.backend.db_path.parent / "project"
        proj.mkdir()
        (proj / "main.py").write_text("def y(): pass\n")

        from sylvan.indexing.pipeline.orchestrator import index_folder
        result = await index_folder(str(proj), name="proj-usage")
        await usage_ctx.backend.commit()
        repo_id = result.repo_id

        import sylvan.session.usage_stats as usage_mod
        usage_mod._accumulator = None

        from sylvan.session.usage_stats import async_get_project_usage, record_usage
        record_usage(repo_id=repo_id, tokens_returned=100, symbols_retrieved=2)
        record_usage(repo_id=repo_id, tokens_returned=50, sections_retrieved=1)

        usage = await async_get_project_usage(usage_ctx.backend, repo_id)
        assert usage["total_tool_calls"] == 2
        assert usage["total_tokens_returned"] == 150
        assert usage["total_symbols_retrieved"] == 2
        assert usage["total_sections_retrieved"] == 1
        assert usage["days_active"] == 1

    async def test_empty_repo_returns_zeros(self, usage_ctx):
        import sylvan.session.usage_stats as usage_mod
        usage_mod._accumulator = None

        from sylvan.session.usage_stats import async_get_project_usage
        usage = await async_get_project_usage(usage_ctx.backend, 99999)
        assert usage["total_tool_calls"] == 0
        assert usage["total_tokens_returned"] == 0
        assert usage["first_used"] is None


class TestGetOverallUsage:
    async def test_aggregates_across_repos(self, usage_ctx):
        proj_a = usage_ctx.backend.db_path.parent / "proj_a"
        proj_a.mkdir()
        (proj_a / "a.py").write_text("def a(): pass\n")
        proj_b = usage_ctx.backend.db_path.parent / "proj_b"
        proj_b.mkdir()
        (proj_b / "b.py").write_text("def b(): pass\n")

        from sylvan.indexing.pipeline.orchestrator import index_folder
        r_a = await index_folder(str(proj_a), name="overall-a")
        r_b = await index_folder(str(proj_b), name="overall-b")
        await usage_ctx.backend.commit()

        import sylvan.session.usage_stats as usage_mod
        usage_mod._accumulator = None

        from sylvan.session.usage_stats import async_get_overall_usage, record_usage
        record_usage(repo_id=r_a.repo_id, tokens_returned=100)
        record_usage(repo_id=r_b.repo_id, tokens_returned=200)

        usage = await async_get_overall_usage(usage_ctx.backend)
        assert usage["repos_used"] >= 2
        assert usage["total_tool_calls"] >= 2
        assert usage["total_tokens_returned"] >= 300
        assert usage["days_active"] >= 1

    async def test_empty_overall_returns_zeros(self, usage_ctx):
        import sylvan.session.usage_stats as usage_mod
        usage_mod._accumulator = None

        from sylvan.session.usage_stats import async_get_overall_usage
        usage = await async_get_overall_usage(usage_ctx.backend)
        assert usage["total_tool_calls"] == 0
        assert usage["repos_used"] == 0
