"""Tests for sylvan.dashboard.app — routes, data helpers, and middleware."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.routing import Route

if TYPE_CHECKING:
    from starlette.requests import Request


class TestUptime:
    """Tests for the _uptime() helper."""

    def test_uptime_minutes_only(self):
        """Uptime shows minutes when under an hour."""
        import sylvan.dashboard.app as app_mod
        from sylvan.dashboard.app import _uptime

        original = app_mod._start_time
        try:
            # Set start time to 5 minutes ago
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
            # Set start time to 2 hours 15 minutes ago
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
            # Set start time to 3 days 5 hours ago
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


class TestCreateDashboardApp:
    """Tests for create_dashboard_app()."""

    def test_returns_starlette_app(self):
        """create_dashboard_app returns a Starlette application."""
        from sylvan.dashboard.app import create_dashboard_app

        app = create_dashboard_app()
        assert isinstance(app, Starlette)

    def test_app_has_routes(self):
        """The app has the expected routes registered."""
        from sylvan.dashboard.app import create_dashboard_app

        app = create_dashboard_app()
        route_paths = [r.path for r in app.routes]
        assert "/" in route_paths
        assert "/quality" in route_paths
        assert "/libraries" in route_paths
        assert "/search" in route_paths
        assert "/api/stats" in route_paths
        assert "/htmx/stats" in route_paths
        assert "/htmx/quality" in route_paths
        assert "/htmx/search" in route_paths


class TestSearchSymbols:
    """Tests for _search_symbols()."""

    async def test_empty_query_returns_empty(self, ctx):
        """Empty or very short query returns no results."""
        from sylvan.dashboard.app import _search_symbols

        result = await _search_symbols("")
        assert result == []

    async def test_short_query_returns_empty(self, ctx):
        """Query shorter than 2 chars returns no results."""
        from sylvan.dashboard.app import _search_symbols

        result = await _search_symbols("x")
        assert result == []

    async def test_no_results_for_unknown(self, ctx):
        """Searching for a nonexistent symbol returns empty list."""
        from sylvan.dashboard.app import _search_symbols

        result = await _search_symbols("xyzzy_nonexistent_symbol_12345")
        assert isinstance(result, list)
        assert len(result) == 0


class TestDashboardRoutes:
    """Integration tests for dashboard HTTP routes.

    Uses httpx AsyncClient with ASGITransport to avoid starting a real server.
    The middleware is replaced to use the test backend from fixtures.
    """

    @pytest.fixture
    def dashboard_app(self, backend, ctx):
        """Create a dashboard app with middleware that uses the test context."""
        from starlette.middleware import Middleware
        from starlette.middleware.base import BaseHTTPMiddleware

        from sylvan.dashboard.app import (
            api_stats,
            libraries,
            overview,
            overview_partial,
            quality,
            quality_partial,
            search,
            search_results,
        )

        async def _test_context_middleware(request: Request, call_next):
            """Use the existing test context instead of creating a new backend."""
            from sylvan.context import using_context

            async with using_context(ctx):
                response = await call_next(request)
            return response

        routes = [
            Route("/", overview),
            Route("/quality", quality),
            Route("/libraries", libraries),
            Route("/search", search),
            Route("/api/stats", api_stats),
            Route("/htmx/stats", overview_partial),
            Route("/htmx/quality", quality_partial),
            Route("/htmx/search", search_results),
        ]
        middleware = [
            Middleware(BaseHTTPMiddleware, dispatch=_test_context_middleware),
        ]
        return Starlette(routes=routes, middleware=middleware)

    async def test_overview_returns_html(self, dashboard_app):
        """GET / returns HTML with 200 status."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_api_stats_returns_json(self, dashboard_app):
        """GET /api/stats returns JSON with overview data."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_symbols" in data
        assert "total_files" in data
        assert "repos" in data
        assert "uptime" in data

    async def test_quality_page_returns_html(self, dashboard_app):
        """GET /quality returns HTML."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/quality")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_libraries_page_returns_html(self, dashboard_app):
        """GET /libraries returns HTML."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/libraries")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_search_page_returns_html(self, dashboard_app):
        """GET /search returns HTML."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/search")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_htmx_stats_returns_html(self, dashboard_app):
        """GET /htmx/stats returns an HTML partial."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/htmx/stats")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_htmx_quality_no_repo_returns_prompt(self, dashboard_app):
        """GET /htmx/quality without repo param returns a prompt message."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/htmx/quality")
        assert response.status_code == 200
        assert "Select a repository" in response.text

    async def test_htmx_search_empty_query(self, dashboard_app):
        """GET /htmx/search with empty query returns results partial."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/htmx/search?q=")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_api_stats_data_structure(self, dashboard_app):
        """API stats response has the expected structure."""
        transport = ASGITransport(app=dashboard_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/stats")
        data = response.json()
        assert isinstance(data["repos"], list)
        assert isinstance(data["libraries"], list)
        assert isinstance(data["total_symbols"], int)
        assert isinstance(data["total_files"], int)
        assert isinstance(data["total_repos"], int)
        assert isinstance(data["total_libraries"], int)
