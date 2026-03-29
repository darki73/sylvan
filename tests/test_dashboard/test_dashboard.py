"""Tests for sylvan.dashboard.app - routes, data helpers, and middleware."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from sylvan.database.orm import (
    ClusterNode,
    CodingSession,
    FileRecord,
    Instance,
    Repo,
    Symbol,
)


class TestUptime:
    """Tests for the _uptime() helper."""

    def test_uptime_minutes_only(self):
        """Uptime shows minutes when under an hour."""
        import sylvan.dashboard.app as app_mod
        from sylvan.dashboard.app import _uptime

        original = app_mod._start_time
        try:
            app_mod._start_time = time.monotonic() - 300
            result = _uptime()
            assert "m" in result
            assert "h" not in result
            assert "d" not in result
        finally:
            app_mod._start_time = original

    def test_uptime_hours_and_minutes(self):
        """Uptime shows hours and minutes when between 1h and 1d."""
        import sylvan.dashboard.app as app_mod

        original = app_mod._start_time
        try:
            app_mod._start_time = time.monotonic() - (2 * 3600 + 15 * 60)
            result = app_mod._uptime()
            assert "h" in result
            assert "m" in result
            assert "d" not in result
        finally:
            app_mod._start_time = original

    def test_uptime_days_and_hours(self):
        """Uptime shows days and hours when over 1 day."""
        import sylvan.dashboard.app as app_mod

        original = app_mod._start_time
        try:
            app_mod._start_time = time.monotonic() - (3 * 86400 + 5 * 3600)
            result = app_mod._uptime()
            assert "d" in result
            assert "h" in result
        finally:
            app_mod._start_time = original

    def test_uptime_zero_minutes(self):
        """Uptime shows 0m when just started."""
        import sylvan.dashboard.app as app_mod

        original = app_mod._start_time
        try:
            app_mod._start_time = time.monotonic()
            result = app_mod._uptime()
            assert result == "0m"
        finally:
            app_mod._start_time = original


class TestFormatDuration:
    """Tests for the _format_duration() helper."""

    def test_seconds_only(self):
        from sylvan.dashboard.app import _format_duration

        assert _format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        from sylvan.dashboard.app import _format_duration

        assert _format_duration(125) == "2m 5s"

    def test_hours_and_minutes(self):
        from sylvan.dashboard.app import _format_duration

        assert _format_duration(7500) == "2h 5m"

    def test_zero(self):
        from sylvan.dashboard.app import _format_duration

        assert _format_duration(0) == "0s"

    def test_exact_minute(self):
        from sylvan.dashboard.app import _format_duration

        assert _format_duration(60) == "1m 0s"

    def test_exact_hour(self):
        from sylvan.dashboard.app import _format_duration

        assert _format_duration(3600) == "1h 0m"


class TestCreateDashboardApp:
    """Tests for create_dashboard_app()."""

    def test_returns_starlette_app(self):
        from sylvan.dashboard.app import create_dashboard_app

        app = create_dashboard_app()
        assert isinstance(app, Starlette)

    def test_app_has_routes(self):
        from sylvan.dashboard.app import create_dashboard_app

        app = create_dashboard_app()
        route_paths = [r.path for r in app.routes]
        assert "/ws/dashboard" in route_paths
        assert "/ws/cluster" in route_paths
        assert "/{path:path}" in route_paths

    def test_no_legacy_routes(self):
        """Legacy Jinja/HTMX routes are not present."""
        from sylvan.dashboard.app import create_dashboard_app

        app = create_dashboard_app()
        route_paths = [r.path for r in app.routes]
        assert "/legacy" not in route_paths
        assert "/htmx/stats" not in route_paths
        assert "/htmx/quality" not in route_paths
        assert "/htmx/search" not in route_paths
        assert "/htmx/session" not in route_paths
        assert "/api/stats" not in route_paths


class TestSearchSymbols:
    """Tests for _search_symbols()."""

    async def test_empty_query_returns_empty(self, ctx):
        from sylvan.dashboard.app import _search_symbols

        result = await _search_symbols("")
        assert result == []

    async def test_short_query_returns_empty(self, ctx):
        from sylvan.dashboard.app import _search_symbols

        result = await _search_symbols("x")
        assert result == []

    async def test_no_results_for_unknown(self, ctx):
        from sylvan.dashboard.app import _search_symbols

        result = await _search_symbols("xyzzy_nonexistent_symbol_12345")
        assert isinstance(result, list)
        assert len(result) == 0

    async def test_returns_matching_symbols(self, ctx):
        """Searching returns matching symbols with correct structure."""
        from sylvan.dashboard.app import _search_symbols

        backend = ctx.backend
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["test-repo", "/test"],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (1, 'src/main.py', 'python', 'abc123', 100)",
            [],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["sym-test-1", 1, "my_dashboard_func", "main.my_dashboard_func", "function", "python", 10, 20, 0, 100],
        )
        await backend.commit()

        result = await _search_symbols("my_dashboard_func")
        assert len(result) >= 1
        sym = result[0]
        assert sym["name"] == "my_dashboard_func"
        assert sym["kind"] == "function"
        assert sym["repo"] == "test-repo"
        assert sym["file"] == "src/main.py"

    async def test_filters_by_repo_name(self, ctx):
        """Repo filter limits results to the specified repo."""
        from sylvan.dashboard.app import _search_symbols

        backend = ctx.backend
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["repo-a", "/a"],
        )
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
            ["repo-b", "/b"],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (1, 'a.py', 'python', 'ha', 50)",
            [],
        )
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (2, 'b.py', 'python', 'hb', 50)",
            [],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["sym-a-1", 1, "shared_dashboard_func", "a.shared_dashboard_func", "function", "python", 1, 5, 0, 50],
        )
        await backend.execute(
            "INSERT INTO symbols (symbol_id, file_id, name, qualified_name, kind, language, "
            "line_start, line_end, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["sym-b-1", 2, "shared_dashboard_func", "b.shared_dashboard_func", "function", "python", 1, 5, 0, 50],
        )
        await backend.commit()

        result = await _search_symbols("shared_dashboard_func", repo_name="repo-a")
        repos_in_result = {s["repo"] for s in result}
        assert "repo-a" in repos_in_result
        assert "repo-b" not in repos_in_result


class TestCombineSessionEfficiency:
    """Tests for _combine_session_efficiency()."""

    def test_empty_sessions_returns_none(self):
        from sylvan.dashboard.app import _combine_session_efficiency

        assert _combine_session_efficiency([]) is None

    def test_zero_equivalent_returns_none(self):
        from sylvan.dashboard.app import _combine_session_efficiency

        sessions = [{"efficiency_returned": 0, "efficiency_equivalent": 0}]
        assert _combine_session_efficiency(sessions) is None

    def test_combines_multiple_sessions(self):
        from sylvan.dashboard.app import _combine_session_efficiency

        sessions = [
            {
                "efficiency_returned": 100,
                "efficiency_equivalent": 200,
                "category_data": {"search": {"calls": 1, "returned": 100, "equivalent": 200}},
            },
            {
                "efficiency_returned": 50,
                "efficiency_equivalent": 300,
                "category_data": {"search": {"calls": 2, "returned": 50, "equivalent": 300}},
            },
        ]
        result = _combine_session_efficiency(sessions)
        assert result is not None
        assert result["total_returned"] == 150
        assert result["total_equivalent"] == 500
        assert result["by_category"]["search"]["calls"] == 3
        assert result["by_category"]["search"]["returned"] == 150
        assert result["by_category"]["search"]["equivalent"] == 500

    def test_reduction_percent_calculated(self):
        from sylvan.dashboard.app import _combine_session_efficiency

        sessions = [{"efficiency_returned": 200, "efficiency_equivalent": 1000, "category_data": {}}]
        result = _combine_session_efficiency(sessions)
        assert result is not None
        assert result["reduction_percent"] == 80.0

    def test_merges_different_categories(self):
        from sylvan.dashboard.app import _combine_session_efficiency

        sessions = [
            {
                "efficiency_returned": 100,
                "efficiency_equivalent": 200,
                "category_data": {"search": {"calls": 1, "returned": 100, "equivalent": 200}},
            },
            {
                "efficiency_returned": 50,
                "efficiency_equivalent": 100,
                "category_data": {"retrieval": {"calls": 3, "returned": 50, "equivalent": 100}},
            },
        ]
        result = _combine_session_efficiency(sessions)
        assert result is not None
        assert "search" in result["by_category"]
        assert "retrieval" in result["by_category"]

    def test_handles_missing_category_data(self):
        from sylvan.dashboard.app import _combine_session_efficiency

        sessions = [
            {"efficiency_returned": 100, "efficiency_equivalent": 200, "category_data": None},
            {"efficiency_returned": 50, "efficiency_equivalent": 100},
        ]
        result = _combine_session_efficiency(sessions)
        assert result is not None
        assert result["by_category"] == {}


class TestGetClusterSessions:
    """Tests for _get_cluster_sessions()."""

    async def test_empty_cluster_returns_empty(self, ctx):
        from sylvan.dashboard.app import _get_cluster_sessions

        result = await _get_cluster_sessions()
        assert result == []

    async def test_returns_node_data(self, ctx):
        from sylvan.dashboard.app import _get_cluster_sessions

        now = datetime.now(UTC).isoformat()
        cs = await CodingSession.create(id="cs-test-1", started_at=now)
        await ClusterNode.create(
            node_id="node-1",
            pid=os.getpid(),
            role="leader",
            coding_session_id=cs.id,
            connected_at=now,
            last_seen=now,
        )

        result = await _get_cluster_sessions()
        assert len(result) == 1
        node = result[0]
        assert node["session_id"] == "node-1"
        assert node["role"] == "leader"
        assert node["coding_session_id"] == "cs-test-1"

    async def test_includes_instance_stats(self, ctx):
        from sylvan.dashboard.app import _get_cluster_sessions

        now = datetime.now(UTC).isoformat()
        cs = await CodingSession.create(id="cs-test-2", started_at=now)
        await ClusterNode.create(
            node_id="node-2",
            pid=os.getpid(),
            role="leader",
            coding_session_id=cs.id,
            connected_at=now,
            last_seen=now,
        )
        await Instance.create(
            instance_id="inst-2",
            node_id="node-2",
            coding_session_id="cs-test-2",
            started_at=now,
            tool_calls=42,
            tokens_returned=500,
            tokens_avoided=1500,
            efficiency_returned=500,
            efficiency_equivalent=2000,
            symbols_retrieved=10,
            queries=5,
        )

        result = await _get_cluster_sessions()
        assert len(result) == 1
        node = result[0]
        assert node["tool_calls"] == 42
        assert node["tokens_returned"] == 500
        assert node["efficiency_returned"] == 500
        assert node["efficiency_equivalent"] == 2000
        assert node["reduction_percent"] == 75.0
        assert node["symbols_retrieved"] == 10

    async def test_node_without_instance(self, ctx):
        """Node without active instance returns zero stats."""
        from sylvan.dashboard.app import _get_cluster_sessions

        now = datetime.now(UTC).isoformat()
        cs = await CodingSession.create(id="cs-test-3", started_at=now)
        await ClusterNode.create(
            node_id="node-3",
            pid=os.getpid(),
            role="follower",
            coding_session_id=cs.id,
            connected_at=now,
            last_seen=now,
        )

        result = await _get_cluster_sessions()
        assert len(result) == 1
        node = result[0]
        assert node["tool_calls"] == 0
        assert node["efficiency_returned"] == 0
        assert node["reduction_percent"] == 0


class TestGetCurrentCodingSessionTotals:
    """Tests for _get_current_coding_session_totals()."""

    async def test_empty_id_returns_empty(self, ctx):
        from sylvan.dashboard.app import _get_current_coding_session_totals

        result = await _get_current_coding_session_totals("")
        assert result == {}

    async def test_missing_session_returns_empty(self, ctx):
        from sylvan.dashboard.app import _get_current_coding_session_totals

        result = await _get_current_coding_session_totals("nonexistent-id")
        assert result == {}

    async def test_returns_session_totals(self, ctx):
        from sylvan.dashboard.app import _get_current_coding_session_totals

        await CodingSession.create(
            id="cs-totals-1",
            started_at=datetime.now(UTC).isoformat(),
            total_tool_calls=100,
            total_efficiency_returned=500,
            total_efficiency_equivalent=2000,
        )

        result = await _get_current_coding_session_totals("cs-totals-1")
        assert result["tool_calls"] == 100
        assert result["efficiency_returned"] == 500
        assert result["efficiency_equivalent"] == 2000


class TestGetCodingSessionHistory:
    """Tests for _get_coding_session_history()."""

    async def test_empty_history(self, ctx):
        from sylvan.dashboard.app import _get_coding_session_history

        result = await _get_coding_session_history()
        assert result == []

    async def test_returns_sessions_ordered(self, ctx):
        """Sessions are returned most recent first."""
        from sylvan.dashboard.app import _get_coding_session_history

        now = datetime.now(UTC)
        await CodingSession.create(
            id="cs-old",
            started_at=(now - timedelta(hours=2)).isoformat(),
            ended_at=(now - timedelta(hours=1)).isoformat(),
            total_tool_calls=10,
        )
        await CodingSession.create(
            id="cs-new",
            started_at=(now - timedelta(minutes=30)).isoformat(),
            total_tool_calls=50,
        )

        result = await _get_coding_session_history()
        assert len(result) == 2
        assert result[0]["id"] == "cs-new"
        assert result[1]["id"] == "cs-old"

    async def test_calculates_duration_for_ended(self, ctx):
        """Duration is calculated for ended sessions."""
        from sylvan.dashboard.app import _get_coding_session_history

        now = datetime.now(UTC)
        await CodingSession.create(
            id="cs-ended",
            started_at=(now - timedelta(hours=2, minutes=15)).isoformat(),
            ended_at=now.isoformat(),
            total_tool_calls=5,
        )

        result = await _get_coding_session_history()
        assert len(result) == 1
        assert "h" in result[0]["duration"]
        assert "m" in result[0]["duration"]

    async def test_calculates_duration_for_active(self, ctx):
        """Active sessions get a duration from start to now."""
        from sylvan.dashboard.app import _get_coding_session_history

        now = datetime.now(UTC)
        await CodingSession.create(
            id="cs-active",
            started_at=(now - timedelta(minutes=10)).isoformat(),
            total_tool_calls=3,
        )

        result = await _get_coding_session_history()
        assert len(result) == 1
        assert result[0]["duration"] != ""

    async def test_reduction_percent(self, ctx):
        """Reduction percentage is calculated for sessions with efficiency data."""
        from sylvan.dashboard.app import _get_coding_session_history

        await CodingSession.create(
            id="cs-eff",
            started_at=datetime.now(UTC).isoformat(),
            total_efficiency_returned=200,
            total_efficiency_equivalent=1000,
            total_tool_calls=5,
        )

        result = await _get_coding_session_history()
        assert len(result) == 1
        assert result[0]["reduction_percent"] == 80.0

    async def test_zero_efficiency_shows_zero_reduction(self, ctx):
        """Session with zero equivalent shows 0% reduction."""
        from sylvan.dashboard.app import _get_coding_session_history

        await CodingSession.create(
            id="cs-zero",
            started_at=datetime.now(UTC).isoformat(),
            total_tool_calls=1,
        )

        result = await _get_coding_session_history()
        assert result[0]["reduction_percent"] == 0

    async def test_respects_limit(self, ctx):
        """Limit parameter restricts number of results."""
        from sylvan.dashboard.app import _get_coding_session_history

        now = datetime.now(UTC)
        for i in range(5):
            await CodingSession.create(
                id=f"cs-limit-{i}",
                started_at=(now - timedelta(hours=i)).isoformat(),
            )

        result = await _get_coding_session_history(limit=3)
        assert len(result) == 3


class TestGetOverviewData:
    """Tests for _get_overview_data()."""

    async def test_empty_database(self, ctx):
        """Overview data with empty database returns zeroes."""
        from sylvan.dashboard.app import _get_overview_data

        data = await _get_overview_data()
        assert data["total_symbols"] == 0
        assert data["total_files"] == 0
        assert data["total_sections"] == 0
        assert data["total_repos"] == 0
        assert data["total_libraries"] == 0
        assert data["repos"] == []
        assert data["libraries"] == []

    async def test_counts_repos_and_libraries(self, ctx):
        """Repos and libraries are counted separately."""
        from sylvan.dashboard.app import _get_overview_data

        now = datetime.now(UTC).isoformat()
        await Repo.create(name="my-repo", source_path="/repo", repo_type="local", indexed_at=now)
        await Repo.create(
            name="lib@1.0",
            source_path="/lib",
            repo_type="library",
            package_name="lib",
            version="1.0",
            indexed_at=now,
        )

        data = await _get_overview_data()
        assert data["total_repos"] == 1
        assert data["total_libraries"] == 1
        assert len(data["repos"]) == 1
        assert len(data["libraries"]) == 1

    async def test_repo_data_structure(self, ctx):
        """Repo entries have the expected fields."""
        from sylvan.dashboard.app import _get_overview_data

        repo = await Repo.create(
            name="test-repo",
            source_path="/test",
            repo_type="local",
            indexed_at="2026-01-01T00:00:00",
            git_head="abcdef1234567890",
        )
        file_rec = await FileRecord.create(
            repo_id=repo.id,
            path="src/main.py",
            language="python",
            content_hash="h1",
            byte_size=100,
        )
        await Symbol.create(
            symbol_id="sym-ov-1",
            file_id=file_rec.id,
            name="func",
            qualified_name="main.func",
            kind="function",
            language="python",
            line_start=1,
            line_end=5,
            byte_offset=0,
            byte_length=50,
        )

        data = await _get_overview_data()
        rd = data["repos"][0]
        assert rd["name"] == "test-repo"
        assert rd["files"] == 1
        assert rd["symbols"] == 1
        assert rd["indexed_at"] == "2026-01-01T00:00:00"
        assert rd["git_head"] == "abcdef12"

    async def test_language_counts(self, ctx):
        """Repo data includes language breakdown."""
        from sylvan.dashboard.app import _get_overview_data

        now = datetime.now(UTC).isoformat()
        repo = await Repo.create(name="lang-repo", source_path="/lang", repo_type="local", indexed_at=now)
        await FileRecord.create(repo_id=repo.id, path="a.py", language="python", content_hash="h1", byte_size=50)
        await FileRecord.create(repo_id=repo.id, path="b.py", language="python", content_hash="h2", byte_size=50)
        await FileRecord.create(repo_id=repo.id, path="c.ts", language="typescript", content_hash="h3", byte_size=50)

        data = await _get_overview_data()
        rd = data["repos"][0]
        assert "languages" in rd
        assert rd["languages"]["python"] == 2
        assert rd["languages"]["typescript"] == 1

    async def test_alltime_efficiency(self, ctx):
        """All-time efficiency aggregates coding sessions and instances."""
        from sylvan.dashboard.app import _get_overview_data

        await CodingSession.create(
            id="cs-ov-1",
            started_at=datetime.now(UTC).isoformat(),
            ended_at=datetime.now(UTC).isoformat(),
            total_efficiency_returned=100,
            total_efficiency_equivalent=500,
            total_tool_calls=10,
        )

        data = await _get_overview_data()
        alltime = data["alltime_efficiency"]
        assert alltime["total_returned"] >= 100
        assert alltime["total_equivalent"] >= 500
        assert alltime["total_calls"] >= 10

    async def test_library_data_structure(self, ctx):
        """Library entries have package info fields."""
        from sylvan.dashboard.app import _get_overview_data

        now = datetime.now(UTC).isoformat()
        await Repo.create(
            name="requests@2.31.0",
            source_path="/lib/requests",
            repo_type="library",
            package_name="requests",
            package_manager="pip",
            version="2.31.0",
            indexed_at=now,
        )

        data = await _get_overview_data()
        assert len(data["libraries"]) == 1
        lib = data["libraries"][0]
        assert lib["name"] == "requests@2.31.0"
        assert lib["package"] == "requests"
        assert lib["manager"] == "pip"
        assert lib["version"] == "2.31.0"


class TestGetQualityData:
    """Tests for _get_quality_data()."""

    async def test_nonexistent_repo(self, ctx):
        from sylvan.dashboard.app import _get_quality_data

        result = await _get_quality_data("does-not-exist")
        assert "error" in result

    async def test_existing_repo_returns_data(self, ctx):
        """Quality data is returned for an existing repo."""
        from sylvan.dashboard.app import _get_quality_data

        now = datetime.now(UTC).isoformat()
        await Repo.create(name="quality-repo", source_path="/quality", repo_type="local", indexed_at=now)

        result = await _get_quality_data("quality-repo")
        assert "error" not in result
        assert result["repo"] == "quality-repo"
        assert "test_coverage" in result
        assert "doc_coverage" in result
        assert "type_coverage" in result
        assert "smells" in result
        assert "smells_by_severity" in result
        assert "security" in result
        assert "security_by_severity" in result
        assert "duplicates" in result


class TestSpaCatchall:
    """Tests for _spa_catchall()."""

    def test_returns_503_when_not_built(self, tmp_path, monkeypatch):
        """Returns 503 when SPA dist does not exist."""
        from sylvan.dashboard.app import _spa_catchall

        # Point the parent to a temp dir with no static/dist
        monkeypatch.setattr(
            "sylvan.dashboard.app.Path",
            lambda *a, **kw: tmp_path / "nonexistent",
        )

        # Build a minimal ASGI scope for Request
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
        request = Request(scope)
        response = _spa_catchall(request)
        assert response.status_code == 503

    def test_serves_html_when_built(self, tmp_path):
        """Returns 200 with HTML when SPA dist exists."""
        from pathlib import Path as RealPath

        from sylvan.dashboard import app as app_mod

        # Create a fake dist with index.html
        dist_dir = RealPath(app_mod.__file__).parent / "static" / "dist"
        if dist_dir.exists() and (dist_dir / "index.html").exists():
            scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
            request = Request(scope)
            response = app_mod._spa_catchall(request)
            assert response.status_code == 200
            assert "text/html" in response.media_type


class TestContextMiddleware:
    """Tests for _context_middleware()."""

    async def test_sets_and_resets_identity_map(self, ctx):
        """Middleware sets an identity map and resets it after the request."""
        from sylvan.context import _identity_map_var
        from sylvan.dashboard.app import _context_middleware

        identity_map_during_request = None

        async def handler(request):
            nonlocal identity_map_during_request
            identity_map_during_request = _identity_map_var.get()
            return PlainTextResponse("ok")

        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
        request = Request(scope)
        response = await _context_middleware(request, handler)
        assert response.status_code == 200
        assert identity_map_during_request is not None

    async def test_resets_on_exception(self, ctx):
        """Identity map is reset even when handler raises."""
        from sylvan.dashboard.app import _context_middleware

        async def bad_handler(request):
            raise ValueError("boom")

        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
        request = Request(scope)
        with pytest.raises(ValueError, match="boom"):
            await _context_middleware(request, bad_handler)
